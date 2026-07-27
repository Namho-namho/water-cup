"""Genesis가 저장한 cup_*.npy 들을 mantaflow용 궤적 txt로 변환.

사용법:
    python make_traj.py <입력폴더> <출력파일.txt>
예:
    python make_traj.py ~/water_cup/traj_tilt_only ~/water_cup/traj_tilt.txt
"""
import numpy as np, os, sys, glob

src = os.path.expanduser(sys.argv[1])
out = os.path.expanduser(sys.argv[2])
files = sorted(glob.glob(f"{src}/cup_*.npy"))
if not files:
    sys.exit(f"cup_*.npy 파일이 없습니다: {src}")

with open(out, 'w') as f:
    for p in files:
        f.write(" ".join(f"{x:.8f}" for x in np.load(p)) + "\n")

t = np.array([[float(x) for x in l.split()] for l in open(out)])
q = t[:, 3:7]
ang = 2 * np.degrees(np.arccos(np.clip(np.abs(q[:, 0]), 0, 1)))
a = (t[2:, :3] - 2*t[1:-1, :3] + t[:-2, :3]) / 0.008**2
v = np.linalg.norm(np.diff(t[:, :3], axis=0), axis=1) / 0.008
print(f"{len(files)} 프레임 -> {out}")
print(f"  이동거리   : {np.linalg.norm(t[-1,:3]-t[0,:3])*1000:.1f} mm")
print(f"  최대 속도  : {v.max():.3f} m/s")
print(f"  최대 가속도: {np.linalg.norm(a,axis=1).max():.2f} m/s^2")
print(f"  자세 변화  : {ang.min():.1f} ~ {ang.max():.1f} deg")
