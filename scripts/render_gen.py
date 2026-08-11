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
