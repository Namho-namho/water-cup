import time as _time
_t0=_time.time()
import bpy, gzip, struct, os, json
import numpy as np
MESH_DIR = os.path.expanduser(os.environ.get("MESH_DIR", "~/water_cup/idp_out"))
OUT_DIR  = os.path.expanduser(os.environ.get("OUT_LABELS", "~/water_cup/heights_out"))
os.makedirs(OUT_DIR, exist_ok=True)
M = json.load(open(f"{MESH_DIR}/meta.json"))
# 카메라 지정 규약은 render_gen.py와 같다. 라벨 격자의 방위각이 여기서 정해진다.
# 방향별 출력 폴더는 부르는 쪽이 OUT_LABELS로 넘긴다 (예: out/0001/height_e).
CAM_NAME = os.environ.get("CAM_NAME", "").strip()
if CAM_NAME:
    if CAM_NAME not in bpy.data.objects:
        raise SystemExit(f"카메라 없음: {CAM_NAME}")
    bpy.context.scene.camera = bpy.data.objects[CAM_NAME]
    print(f"카메라: {CAM_NAME}", flush=True)
# 측정기는 이 스크립트와 같은 폴더에 있는 것을 쓴다. 세라프처럼 $HOME이 계산 노드에
# 공유되지 않는 환경에서 ~/water_cup 을 못 찾는 문제를 피한다. HFT_PATH로 덮어쓸 수 있다.
_HFT = os.environ.get("HFT_PATH", "")
if not _HFT:
    _here = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else ""
    _HFT = os.path.join(_here, "height_field_tool.py")
    if not os.path.exists(_HFT):
        _HFT = os.path.expanduser("~/water_cup/height_field_tool.py")
print(f"측정기: {_HFT}", flush=True)
exec(open(_HFT).read())
CUP_BASE_Z = M['cup_bottom_t']
H=M['H']; S=float(M['gs'][2])
GX0,GY0,GZ0 = M['cupCenterX'], M['cupBottom'], M['cupCenterZ']
TF=M['TFRAME']; SET=M['SETTLE_T']; NT=M['NT']
CEN=np.array([M['gs'][0]/2, M['gs'][1]/2, M['gs'][2]/2])
traj=[[float(x) for x in l.split()] for l in open(os.path.expanduser(M['traj_file']))]
T0=traj[0]
water_obj=bpy.data.objects["water"]
def rb(p):
    with gzip.open(p,'rb') as f: data=f.read()
    nv=struct.unpack_from('<i',data,0)[0]
    verts=np.frombuffer(data,dtype=np.float32,count=nv*3,offset=4).reshape(-1,3)
    off=4+nv*12
    nn=struct.unpack_from('<i',data,off)[0]; off+=4+nn*12
    nt=struct.unpack_from('<i',data,off)[0]; off+=4
    tris=np.frombuffer(data,dtype=np.int32,count=nt*3,offset=off).reshape(-1,3)
    return verts.astype(np.float64), tris
n=0
azim={}; gang={}; bad=[]
# 이보다 유효 셀이 적은 프레임은 못 쓸 라벨로 보고 NaN 처리한다 (전체 616셀 중)
MIN_VALID=int(os.environ.get("MIN_VALID", 62))
_S=int(os.environ.get("F_START",0)); _E=int(os.environ.get("F_END",NT-1))
print(f"[labels] frames {_S}~{_E}", flush=True)
for i in range(_S, _E+1):
    sf=int(round(SET+i*TF))
    p=f"{MESH_DIR}/mesh_{sf:04d}.bobj.gz"
    if not os.path.exists(p): continue
    v,t=rb(p)
    g=v*S+CEN
    w=np.stack([(g[:,0]-GX0)*H+T0[0],(g[:,2]-GZ0)*H+T0[1],(g[:,1]-GY0)*H+T0[2]],axis=1)
    old=water_obj.data
    new=bpy.data.meshes.new(f"m{i}")
    new.from_pydata(w.tolist(),[],t.tolist())
    water_obj.data=new
    bpy.data.meshes.remove(old)
    pose=np.array(traj[i][:7])
    hf=extract_height_field(water_obj, pose)
    nv=int(np.count_nonzero(~np.isnan(hf)))
    # 유효 셀이 없거나 지나치게 적으면 그 프레임만 버린다(전부 NaN으로 저장).
    # 물이 컵 밖에 있는 시뮬(정착 캐시 오정렬 등)에서도 시퀀스 전체가 날아가지 않게 한다.
    if nv < MIN_VALID:
        print(f"[warn] f{i:04d} 유효 셀 {nv}개 (<{MIN_VALID}) -> NaN 프레임으로 저장", flush=True)
        hf=np.full_like(hf, np.nan)
        bad.append(i); nv=0
    np.save(f"{OUT_DIR}/height_{i:04d}.npy", hf)
    azim[i]=grid_azimuth_deg(pose); gang[i]=grid_angle_deg(pose)
    n+=1
    if i%30==0:
        vv=hf[~np.isnan(hf)]
        if vv.size:
            print(f"[{i}/{NT}] 유효 {vv.size} 평균 {vv.mean()*1000:.1f}mm 폭 {(vv.max()-vv.min())*1000:.1f}mm", flush=True)
        else:
            print(f"[{i}/{NT}] 유효 0 — 광선이 수면을 못 찾음", flush=True)
json.dump({'label_frame':LABEL_FRAME, 'grid_plane':GRID_PLANE, 'cam_azim':CAM_AZIM,
           'camera':CAM_NAME or (bpy.context.scene.camera.name
           if bpy.context.scene.camera else None),
           'traj_file':M['traj_file'], 'grid_n':GRID_N, 'grid_r':CUP_INNER_R,
           'sample_r':SAMPLE_R,
           'azim_deg':{str(k):v for k,v in sorted(azim.items())},
           'grid_angle_deg':{str(k):v for k,v in sorted(gang.items())}},
          open(f"{OUT_DIR}/label_meta.json",'w'), indent=1)
print(f"완료 {n}개 -> {OUT_DIR}", flush=True)
if bad:
    print(f"[warn] 못 쓰는 프레임 {len(bad)}/{n}개: {bad[:20]}{' ...' if len(bad)>20 else ''}", flush=True)
    print("[warn] 첫 프레임부터 비었다면 물이 컵 밖에 있는 시뮬이다. "
          "scripts/debug_frame.py 로 메시 위치를 확인하라", flush=True)

import csv as _csv, datetime as _dtm
_dt=_time.time()-_t0
_log=os.path.expanduser('~/water_cup/timing_log.csv')
_new=not os.path.exists(_log)
with open(_log,'a',newline='') as _f:
    _w=_csv.writer(_f)
    if _new: _w.writerow(['datetime','scenario','stage','seconds','detail'])
    _w.writerow([_dtm.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                 os.path.basename(MESH_DIR).replace('idp_',''),'labels',f'{_dt:.0f}',
                 f'frames={NT} frame={LABEL_FRAME}/{GRID_PLANE} cam={CAM_NAME or "-"}'])
print(f'[timing] labels: {_dt/60:.1f}분', flush=True)
