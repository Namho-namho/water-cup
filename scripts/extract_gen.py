import time as _time
_t0=_time.time()
import bpy, gzip, struct, os, json
import numpy as np
MESH_DIR = os.path.expanduser(os.environ.get("MESH_DIR", "~/water_cup/idp_out"))
OUT_DIR  = os.path.expanduser(os.environ.get("OUT_LABELS", "~/water_cup/heights_out"))
os.makedirs(OUT_DIR, exist_ok=True)
M = json.load(open(f"{MESH_DIR}/meta.json"))
exec(open(os.path.expanduser("~/water_cup/height_field_tool.py")).read())
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
    hf=extract_height_field(water_obj, np.array(traj[i][:7]))
    np.save(f"{OUT_DIR}/height_{i:04d}.npy", hf)
    n+=1
    if i%30==0:
        vv=hf[~np.isnan(hf)]
        print(f"[{i}/{NT}] 유효 {len(vv)} 평균 {vv.mean()*1000:.1f}mm 폭 {(vv.max()-vv.min())*1000:.1f}mm", flush=True)
print(f"완료 {n}개 -> {OUT_DIR}", flush=True)

import csv as _csv, datetime as _dtm
_dt=_time.time()-_t0
_log=os.path.expanduser('~/water_cup/timing_log.csv')
_new=not os.path.exists(_log)
with open(_log,'a',newline='') as _f:
    _w=_csv.writer(_f)
    if _new: _w.writerow(['datetime','scenario','stage','seconds','detail'])
    _w.writerow([_dtm.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                 os.path.basename(MESH_DIR).replace('idp_',''),'labels',f'{_dt:.0f}',
                 f'frames={NT}'])
print(f'[timing] labels: {_dt/60:.1f}분', flush=True)
