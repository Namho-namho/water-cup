#!/usr/bin/env python3
"""데이터셋 전체 요약표. 궤적별 조건과 물 거동, 넘침 여부를 한 표로 본다.

    python3 scripts/dataset_summary.py [~/water_cup/dataset_ariel]
"""
import csv, glob, os, sys
import numpy as np

RIM = 0.094      # 컵 테두리 (안바닥 기준)
DS = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else '~/water_cup/dataset_ariel')
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = {int(r['idx']): r for r in csv.DictReader(open(f'{REPO}/traj/batch/params.csv'))}

rows = []
for d in sorted(glob.glob(f'{DS}/[0-9]*')):
    idx = int(os.path.basename(d))
    fs = sorted(glob.glob(f'{d}/height_e/height_*.npy'))
    if not fs:
        continue
    H = [np.load(f) for f in fs]
    val = np.array([int((~np.isnan(h)).sum()) for h in H])
    mx = np.array([np.nanmax(h) for h in H]) * 1000
    sp = np.array([np.nanmax(h) - np.nanmin(h) for h in H]) * 1000
    mean = np.array([np.nanmean(h) for h in H]) * 1000
    over = int((mx > RIM * 1000).sum())
    t = np.loadtxt(f'{REPO}/traj/batch/traj_{idx:04d}.txt')
    a = np.gradient(np.gradient(t[:, :3], 0.008, axis=0), 0.008, axis=0)
    ang = np.degrees(2 * np.arccos(np.clip(np.abs(t[:, 3]), 0, 1)))
    png = len(glob.glob(f'{d}/*.png'))
    p = P[idx]
    rows.append(dict(idx=idx, kind=p['kind'], water=float(p['water']) * 1000,
                     acc=float(np.linalg.norm(a, axis=1).max()), tilt=float(ang.max()),
                     n=len(H), png=png, vmin=int(val.min()), vmax=int(val.max()),
                     hmax=float(mx.max()), spmin=float(sp.min()), spmax=float(sp.max()),
                     over=over, drop=float(mean[0] - mean[-1])))

print(f"{'idx':>3} {'유형':<7}{'수위':>5} {'가속':>5} {'기울기':>6} {'프레임':>5} {'이미지':>6} "
      f"{'유효셀':>9} {'최고':>7} {'기울기폭':>12} {'테두리초과':>10} {'수위감소':>8}")
for r in rows:
    print(f"{r['idx']:3d} {r['kind']:<7}{r['water']:4.0f}mm {r['acc']:5.2f} {r['tilt']:5.1f}도 "
          f"{r['n']:5d} {r['png']:6d} {r['vmin']:4d}~{r['vmax']:<4d} {r['hmax']:6.1f}mm "
          f"{r['spmin']:5.1f}~{r['spmax']:5.1f}mm {r['over']:4d}/{r['n']:<4d} {r['drop']:+7.1f}mm")

ov = [r for r in rows if r['over'] > 0]
no = [r for r in rows if r['over'] == 0]
print(f"\n넘침(테두리 94mm 초과 프레임 있음) {len(ov)}개: "
      + ", ".join(f"{r['idx']}({r['kind']},{r['water']:.0f}mm,{r['over']}프레임)" for r in ov))
print(f"안 넘침 {len(no)}개: " + ", ".join(str(r['idx']) for r in no))
a = np.array([r['acc'] for r in rows])
v = np.array([r['vmin'] for r in rows])
print(f"\n최대 가속도 {a.min():.2f}~{a.max():.2f} m/s^2 (중앙 {np.median(a):.2f})")
print(f"유효 셀 최소값의 범위 {v.min()}~{v.max()} (616이면 전 프레임 꽉 참)")
print(f"프레임 합계 {sum(r['n'] for r in rows)} (라벨 x4 = {sum(r['n'] for r in rows)*4}, 이미지 {sum(r['png'] for r in rows)})")
for w in (55, 65, 75, 85):
    g = [r for r in rows if abs(r['water'] - w) < 1]
    if g:
        print(f"  수위 {w}mm: {len(g)}개, 넘친 궤적 {sum(1 for r in g if r['over']>0)}개, "
              f"기울기폭 최대 {max(r['spmax'] for r in g):.1f}mm")
