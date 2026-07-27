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
    cup.location=traj[j][:3]
    cup.rotation_quaternion=tuple(traj[j][3:7])
bpy.app.handlers.frame_change_pre.clear()
bpy.app.handlers.frame_change_pre.append(update)
sc=bpy.context.scene
sc.frame_start=0; sc.frame_end=NT-1
sc.cycles.transmission_bounces=12
sc.cycles.max_bounces=16
sc.cycles.samples=64
sc.render.fps=int(round(1.0/M['DT_REAL']))
sc.render.image_settings.file_format='FFMPEG'
sc.render.ffmpeg.format='MPEG4'; sc.render.ffmpeg.codec='H264'
sc.render.filepath=os.path.expanduser(os.environ.get("OUT_VIDEO","~/water_cup/render/out"))
print(f"렌더 준비: {NT}프레임, fps={sc.render.fps}", flush=True)
