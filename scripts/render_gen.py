import bpy, gzip, struct, os, json, sys
import numpy as np
MESH_DIR = os.path.expanduser(os.environ.get("MESH_DIR", "~/water_cup/idp_out"))
M = json.load(open(f"{MESH_DIR}/meta.json"))
H=M['H']; S=float(M['gs'][2])
GX0,GY0,GZ0 = M['cupCenterX'], M['cupBottom'], M['cupCenterZ']
TF=M['TFRAME']; SET=M['SETTLE_T']; NT=M['NT']
CEN=np.array([M['gs'][0]/2, M['gs'][1]/2, M['gs'][2]/2])
traj=[[float(x) for x in l.split()] for l in open(os.path.expanduser(M['traj_file']))]
T0=traj[0]
water=bpy.data.objects["water"]; cup=bpy.data.objects["cup"]

# ---- 학습용 데이터셋 모드 ----
# 컵을 숨기고 배경을 흰색으로 깔아, 물만 보이는 이미지를 만든다.
# 컵 밖으로 튀어나간 물은 메시에서 지운다(삼각형 단위 판정).
# 물 재질(투명+굴절+Volume Absorption)은 그대로 둔다. 수면 모양은 반사·굴절과
# 두께에 따른 흡수로 읽어야 하므로 건드리면 안 된다.
WATER_ONLY = os.environ.get("WATER_ONLY", "0") == "1"
# 컵 밖 물을 지우는 방식
#   cylinder (기본) : 컵 안반경 원통과 불리언 교집합. 메시가 닫힌 채로 잘려서 절단면이
#                     물-유리 접촉면처럼 매끈하다. 컵 안에 담긴 물만 남는다.
#   component       : 컵 안에 걸쳐 있는 연결 덩어리만 남긴다. 자르지 않아 절단면이 없지만
#                     컵에 붙어 흘러내리는 물은 그대로 보인다.
#   radius          : 반지름으로 삼각형을 잘라낸다. 물 본체를 가로질러 자르면 메시가 열려
#                     그 자리가 하늘색 계단 모양으로 렌더된다(부피 흡수가 깨짐). 쓰지 말 것.
#   off             : 아무것도 안 지운다
CLIP_MODE = os.environ.get("WATER_CLIP", "cylinder").strip().lower()
CLIP_R = float(os.environ.get("WATER_CLIP_R_MM", M['cup_inner_r']*1000 + 3.0))/1000.0
# 컵 안으로 치는 판정 여유(mm). 표면 재구성이 입자보다 2~3mm 바깥에 표면을 만든다.
IN_MARGIN = float(os.environ.get("WATER_IN_MARGIN_MM", 3.0))/1000.0
# 컵 테두리 위로 솟은 물을 자를지. 0이면 넘치는 물줄기까지 그대로 렌더한다.
CLIP_RIM = os.environ.get("WATER_CLIP_RIM", "0") == "1"
RIM_Z = M['cup_height']          # 컵 로컬 z. 안바닥(=bottom_t) 위로 94mm

def _quat_m(q):
    w,x,y,z = q
    return np.array([[1-2*(y*y+z*z), 2*(x*y-w*z),   2*(x*z+w*y)],
                     [2*(x*y+w*z),   1-2*(x*x+z*z), 2*(y*z-w*x)],
                     [2*(x*z-w*y),   2*(y*z+w*x),   1-2*(x*x+y*y)]])

def _components(nv, t):
    """꼭짓점을 공유하는 삼각형끼리 묶는다 (union-find). 반환: 꼭짓점별 덩어리 번호."""
    parent = np.arange(nv)
    def find(x):
        r = x
        while parent[r] != r: r = parent[r]
        while parent[x] != r: parent[x], x = r, parent[x]
        return r
    for a, b, c in t:
        ra, rb, rc = find(a), find(b), find(c)
        if rb != ra: parent[rb] = ra
        if rc != ra: parent[rc] = ra
    return np.array([find(i) for i in range(nv)])

_CLIP_CYL = None

def clip_water(w, t, pose):
    """컵 밖으로 나간 물을 지운다. 반환: (꼭짓점, 삼각형)."""
    if CLIP_MODE in ("off", "cylinder"):   # cylinder는 불리언 모디파이어가 처리한다
        return w, t
    loc = (w - np.array(pose[:3])) @ _quat_m(pose[3:7])      # 월드 -> 컵 로컬
    rr = loc[:,0]**2 + loc[:,1]**2
    if CLIP_MODE == "radius":
        keep = rr <= CLIP_R**2
        if CLIP_RIM:
            keep &= loc[:,2] <= RIM_Z
        tk = keep[t].all(axis=1)
    else:
        # 컵 안(안반경+여유, 안바닥~테두리)에 꼭짓점이 하나라도 있는 덩어리만 남긴다.
        inside = ((rr <= (M['cup_inner_r'] + IN_MARGIN)**2)
                  & (loc[:,2] >= M['cup_bottom_t'] - 0.002) & (loc[:,2] <= RIM_Z))
        if not inside.any():
            return w, t[:0]
        comp = _components(len(w), t)
        good = np.zeros(len(w), dtype=bool)
        good[np.isin(comp, np.unique(comp[inside]))] = True
        tk = good[t].all(axis=1)
        if CLIP_RIM:
            tk &= (loc[:,2] <= RIM_Z)[t].all(axis=1)
    if tk.all():
        return w, t
    idx = np.full(len(w), -1, dtype=np.int64)
    used = np.unique(t[tk])
    idx[used] = np.arange(len(used))
    return w[used], idx[t[tk]]
def rb(p):
    with gzip.open(p,'rb') as f: data=f.read()
    nv=struct.unpack_from('<i',data,0)[0]
    verts=np.frombuffer(data,dtype=np.float32,count=nv*3,offset=4).reshape(-1,3)
    off=4+nv*12
    nn=struct.unpack_from('<i',data,off)[0]; off+=4+nn*12
    nt=struct.unpack_from('<i',data,off)[0]; off+=4
    tris=np.frombuffer(data,dtype=np.int32,count=nt*3,offset=off).reshape(-1,3)
    return verts.astype(np.float64), tris
def update(scene):
    i=scene.frame_current
    sf=int(round(SET+i*TF))
    p=f"{MESH_DIR}/mesh_{sf:04d}.bobj.gz"
    if not os.path.exists(p): return
    v,t=rb(p)
    g=v*S+CEN
    w=np.stack([(g[:,0]-GX0)*H+T0[0], (g[:,2]-GZ0)*H+T0[1], (g[:,1]-GY0)*H+T0[2]],axis=1)
    if WATER_ONLY:
        w,t=clip_water(w,t,traj[min(i,NT-1)])
        if len(t)==0: return
    old=water.data
    new=bpy.data.meshes.new(f"m{i}")
    new.from_pydata(w.tolist(),[],t.tolist())
    new.validate(verbose=False)
    import bmesh
    bm=bmesh.new(); bm.from_mesh(new)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(new); bm.free()
    for pl in new.polygons: pl.use_smooth=True
    if "water_mat" in bpy.data.materials: new.materials.append(bpy.data.materials["water_mat"])
    water.data=new
    bpy.data.meshes.remove(old)
    if WATER_ONLY:
        # 잘리는지 감시: 원통 절단 뒤 남는 물이 화면 밖으로 나가면 경고한다.
        # 카메라 배치는 25개 궤적을 다 담도록 맞춰져 있지만, 예상보다 높이 솟는
        # 프레임이 나올 수 있어 실행 중에 확인한다.
        _loc=(w-np.array(traj[min(i,NT-1)][:3])) @ _quat_m(traj[min(i,NT-1)][3:7])
        _k=(_loc[:,0]**2+_loc[:,1]**2) <= CLIP_R**2
        if _k.any():
            _co=scene.camera
            _d2=bpy.context.evaluated_depsgraph_get()
            _Vm=np.array(_co.matrix_world.inverted())
            _Pm=np.array(_co.calc_matrix_camera(_d2, x=int(scene.render.resolution_x),
                                                y=int(scene.render.resolution_y)))
            _q=(np.concatenate([w[_k],np.ones((int(_k.sum()),1))],1)@_Vm.T)@_Pm.T
            _ww=_q[:,3]; _ok=_ww>1e-9
            _u=_q[_ok,0]/_ww[_ok]*0.5+0.5; _v=_q[_ok,1]/_ww[_ok]*0.5+0.5
            _out=((_u<0)|(_u>1)|(_v<0)|(_v>1)).mean() if _ok.any() else 0.0
            if _out>0:
                print(f"[warn] f{i:04d} 물의 {_out*100:.1f}%가 화면 밖 "
                      f"(u {_u.min():.2f}~{_u.max():.2f} v {_v.min():.2f}~{_v.max():.2f})", flush=True)
    if WATER_ONLY and CLIP_MODE=='cylinder' and _CLIP_CYL is not None:
        from mathutils import Quaternion as _Q, Vector as _V
        _q=_Q(tuple(traj[i][3:7]))
        _CLIP_CYL.location=_V(traj[i][:3]) + (_q @ _V((0,0,M['cup_bottom_t'])))
        _CLIP_CYL.rotation_mode='QUATERNION'; _CLIP_CYL.rotation_quaternion=_q
    j=min(i,NT-1)
    cup.rotation_mode='QUATERNION'
    cup.location=traj[i][:3]
    cup.rotation_quaternion=tuple(traj[i][3:7])
    mk=bpy.data.objects.get('cup_marker_x')
    if mk is not None:
        from mathutils import Quaternion, Vector
        q=Quaternion(tuple(traj[i][3:7]))
        off=q @ Vector((0.0335, 0.0, 0.050))   # 컵 로컬 +x 바깥면, 높이 50mm
        mk.location=Vector(traj[i][:3]) + off
        mk.rotation_mode='QUATERNION'
        mk.rotation_quaternion=q
bpy.app.handlers.frame_change_pre.clear()
bpy.app.handlers.frame_change_pre.append(update)
sc=bpy.context.scene
_cam=os.environ.get("CAM_NAME")
if _cam and _cam in bpy.data.objects:
    sc.camera=bpy.data.objects[_cam]
    print(f"카메라: {_cam}", flush=True)
sc.render.use_multiview=False

# 마커는 위치 갱신은 계속 하되(디버그용) 렌더에서는 기본으로 숨긴다.
# 라벨 격자를 카메라 기준으로 뽑으므로 학습 이미지에 컵 회전 단서를 남기지 않는다.
_show_marker = os.environ.get("SHOW_MARKER", "0") == "1"
_mk = bpy.data.objects.get('cup_marker_x')
if _mk is not None:
    _mk.hide_render = not _show_marker
    print(f"마커: {'표시' if _show_marker else '숨김'}", flush=True)

if WATER_ONLY and CLIP_MODE == 'cylinder':
    # 컵 안반경 원통과 불리언 교집합. 메시가 닫힌 채로 잘려서 절단면이 물-유리 접촉면
    # 처럼 매끈하게 나온다(삼각형 단위로 자를 때 생기는 열린 면 문제가 없다).
    import bmesh as _bm
    _me = bpy.data.meshes.new('clip_cyl')
    _bmm = _bm.new()
    _bm.ops.create_cone(_bmm, cap_ends=True, segments=96, radius1=CLIP_R, radius2=CLIP_R,
                        depth=0.60)
    _bm.ops.translate(_bmm, verts=_bmm.verts, vec=(0, 0, 0.60/2 - 0.005))
    _bmm.to_mesh(_me); _bmm.free()
    _cyl = bpy.data.objects.new('clip_cyl', _me)
    bpy.context.scene.collection.objects.link(_cyl)
    _cyl.hide_render = True
    _mod = water.modifiers.new('cup_clip', 'BOOLEAN')
    _mod.operation = 'INTERSECT'; _mod.solver = 'EXACT'; _mod.object = _cyl
    _CLIP_CYL = _cyl
    print(f"WATER_ONLY: 원통 불리언 절단 r={CLIP_R*1000:.0f}mm", flush=True)

if WATER_ONLY:
    # 컵과 마커를 숨긴다
    for _n in ('cup', 'cup_marker_x'):
        _o = bpy.data.objects.get(_n)
        if _o is not None: _o.hide_render = True
    # 월드 배경을 흰색으로
    if sc.world is None:
        sc.world = bpy.data.worlds.new('white_world')
    sc.world.use_nodes = True
    _bg = sc.world.node_tree.nodes.get('Background')
    if _bg is None:
        _bg = sc.world.node_tree.nodes.new('ShaderNodeBackground')
        sc.world.node_tree.links.new(
            _bg.outputs[0], sc.world.node_tree.nodes['World Output'].inputs['Surface'])
    _bg.inputs[0].default_value = (1, 1, 1, 1)
    _bg.inputs[1].default_value = 1.0
    # 바닥 평면도 흰색으로. 그림자·음영이 남지 않도록 방출 재질을 쓴다
    _pl = bpy.data.objects.get('Plane')
    if _pl is not None:
        _wm = bpy.data.materials.new('white_bg')
        _wm.use_nodes = True
        _nt = _wm.node_tree
        _nt.nodes.clear()
        _em = _nt.nodes.new('ShaderNodeEmission')
        _em.inputs[0].default_value = (1, 1, 1, 1)
        _em.inputs[1].default_value = 1.0
        _out = _nt.nodes.new('ShaderNodeOutputMaterial')
        _nt.links.new(_em.outputs[0], _out.inputs['Surface'])
        _pl.data.materials.clear()
        _pl.data.materials.append(_wm)
    # 흰색이 회색으로 눌리지 않도록 표준 변환을 쓴다
    sc.view_settings.view_transform = 'Standard'
    print(f"WATER_ONLY: 컵 숨김, 흰 배경, 물 거르기={CLIP_MODE}"
          f"{', 테두리 위 제거' if CLIP_RIM else ', 넘치는 물 유지'}", flush=True)
sc.frame_start=int(os.environ.get("F_START", 0))
sc.frame_end=int(os.environ.get("F_END", NT-1))
print('[render] frames %d~%d' % (sc.frame_start, sc.frame_end), flush=True)
sc.cycles.transmission_bounces=12
sc.cycles.max_bounces=16
sc.cycles.samples=64
sc.render.fps=int(round(1.0/M['DT_REAL']))
if os.environ.get("IMG_MODE") == "1":
    sc.render.image_settings.file_format='PNG'
else:
    sc.render.image_settings.file_format='FFMPEG'
sc.render.ffmpeg.format='MPEG4'; sc.render.ffmpeg.codec='H264'
sc.render.filepath=os.path.expanduser(os.environ.get("OUT_VIDEO","~/water_cup/render/out"))
print(f"렌더 준비: {NT}프레임, fps={sc.render.fps}", flush=True)

# ---- GPU 장치 설정 (서버용) ----
try:
    _prefs = bpy.context.preferences.addons['cycles'].preferences
    _ok = None
    for _t in ('OPTIX', 'CUDA'):
        _prefs.compute_device_type = _t
        _prefs.get_devices()
        if any(d.type == _t for d in _prefs.devices):
            for d in _prefs.devices:
                d.use = (d.type == _t)
            _ok = _t
            break
    if _ok:
        sc.cycles.device = 'GPU'
        print('[gpu] %s | %s' % (_ok, [d.name for d in _prefs.devices if d.use]), flush=True)
    else:
        sc.cycles.device = 'CPU'
        print('[gpu] GPU 없음 -> CPU 사용', flush=True)
except Exception as _e:
    print('[gpu] 설정 실패:', _e, flush=True)
