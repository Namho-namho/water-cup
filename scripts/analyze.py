"""시뮬 결과 검증: 부피 보존 / 누수 / 넘침 / 수면 기울기.

사용법:
    python analyze.py <메시폴더> [라벨폴더]
예:
    python analyze.py ~/water_cup/idp_tilt ~/water_cup/heights_tilt
"""
import gzip, struct, os, sys, json
import numpy as np

d = os.path.expanduser(sys.argv[1])
M = json.load(open(f"{d}/meta.json"))
H = M['H']; S = float(M['gs'][2])
CEN = np.array([M['gs'][0]/2, M['gs'][1]/2, M['gs'][2]/2])
TF = M['TFRAME']; SET = M['SETTLE_T']; NT = M['NT']
traj = [[float(x) for x in l.split()] for l in open(os.path.expanduser(M['traj_file']))]

def read_bobj(p):
    with gzip.open(p, 'rb') as f: data = f.read()
    nv = struct.unpack_from("<i", data, 0)[0]
    verts = np.frombuffer(data, dtype=np.float32, count=nv*3, offset=4).reshape(-1, 3)
    off = 4 + nv*12
    nn = struct.unpack_from("<i", data, off)[0]; off += 4 + nn*12
    nt = struct.unpack_from("<i", data, off)[0]; off += 4
    tris = np.frombuffer(data, dtype=np.int32, count=nt*3, offset=off).reshape(-1, 3)
    return verts.astype(np.float64), tris

def volume_ml(v, t):
    a, b, c = v[t[:,0]], v[t[:,1]], v[t[:,2]]
    return abs(np.einsum('ij,ij->i', a, np.cross(b, c)).sum()/6.0) * (S**3) * (H**3) * 1e6

def qrot(q, v):
    w, x, y, z = q
    t = 2*np.cross([x, y, z], v)
    return v + w*t + np.cross([x, y, z], t)

def cup_frame(i):
    """궤적 i번째의 컵 안바닥 중심과 축 (격자 좌표, 회전 반영)"""
    p = traj[i]
    base = np.array([M['cupCenterX'] + (p[0]-traj[0][0])/H,
                     M['cupBottom']  + (p[2]-traj[0][2])/H + M['cup_bottom_t']/H,
                     M['cupCenterZ'] + (p[1]-traj[0][1])/H])
    aw = qrot(p[3:7], np.array([0.0, 0.0, 1.0]))
    axis = np.array([aw[0], aw[2], aw[1]])
    return base, axis/np.linalg.norm(axis)

print(f"=== {os.path.basename(d)} ===")
print(f"궤적 {NT}프레임 ({(NT-1)*M['DT_REAL']:.2f}초), 수위 {M['water_level']*1000:.0f}mm")
print()
print("frame |  부피(mL) | 누수(격자) | 컵밖(%) | 테두리위(%)")
vols = []; outs = []
for i in range(0, NT, max(1, NT//8)):
    sf = int(round(SET + i*TF))
    p = f"{d}/mesh_{sf:04d}.bobj.gz"
    if not os.path.exists(p): continue
    v, t = read_bobj(p)
    ml = volume_ml(v, t); vols.append(ml)
    g = v*S + CEN
    base, axis = cup_frame(i)
    dv = g - base
    h = dv @ axis
    r = np.linalg.norm(dv - np.outer(h, axis), axis=1)
    leak = h.min()
    out = (r > M['cup_outer_r']/H).mean()*100
    above = (h > (M['cup_height']-M['cup_bottom_t'])/H).mean()*100
    print(f"{i:>5} | {ml:>9.2f} | {leak:>+10.1f} | {out:>6.1f} | {above:>7.1f}")
if vols:
    print()
    print(f"부피 변화 : {vols[0]:.2f} -> {vols[-1]:.2f} mL ({(vols[-1]/vols[0]-1)*100:+.2f}%)")
    print(f"변동 범위 : {min(vols):.2f} ~ {max(vols):.2f} mL")
    print("  [기준] FLIP Fluids 동일 시나리오 -13.9% / 누수는 -3 이내면 정상")
    if any(r > 1.0 for r in outs):
        print("  ※ 넘침이 발생한 케이스입니다. 컵 밖으로 나온 물이 얇게 퍼지면")
        print("     표면 재구성이 부피를 과대평가하고, 누수 열도 바닥에 고인 물을 재므로")
        print("     이 두 지표는 넘침 구간에서 의미가 없습니다.")

if len(sys.argv) > 2:
    L = os.path.expanduser(sys.argv[2])
    R = 0.030
    ts, ms = [], []
    for i in range(NT):
        p = f"{L}/height_{i:04d}.npy"
        if not os.path.exists(p): continue
        h = np.load(p); n = h.shape[0]
        xs = np.linspace(-R, R, n); X, Y = np.meshgrid(xs, xs)
        m = ~np.isnan(h)
        A = np.c_[X[m], Y[m], np.ones(m.sum())]
        c, *_ = np.linalg.lstsq(A, h[m], rcond=None)
        ts.append(np.hypot(c[0], c[1]) * 2 * 0.027 * 1000)
        ms.append(np.nanmean(h)*1000)
    if ts:
        ts = np.array(ts); ms = np.array(ms)
        print()
        print(f"=== 라벨 {len(ts)}개 ===")
        print(f"수면 기울기 : 평균 {ts.mean():.2f} / RMS {np.sqrt((ts**2).mean()):.2f} / 최대 {ts.max():.2f} mm")
        print(f"평균 수위   : {ms.min():.1f} ~ {ms.max():.1f} mm")
