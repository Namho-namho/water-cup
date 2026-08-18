#!/usr/bin/env python3
"""WATER_ONLY 렌더 이미지를 전수 검사한다.

    python3 scripts/check_renders.py <out/XXXX 폴더> [--cams e,n,w,s]

검사 항목
  1) 화면 밖 : 물 픽셀이 이미지 경계(첫/끝 행·열)에 닿으면 잘린 것이다
  2) 인공 절단 : 물 윗변이 부자연스럽게 평평한 프레임.
     45도 부감에서 수면은 타원 호로 보여 윗변이 폭의 30~50%만큼 휜다.
     무언가가 앞을 가리거나 메시가 수평으로 잘리면 윗변이 직선이 된다.
     - 휨 비율 = (윗변 최대y - 최소y) / 물 폭
     - 실제 이미지로 보정: 가려진 프레임 0.07~0.08, 정상 0.29~1.14
  3) 빈 프레임 : 물 픽셀이 거의 없는 프레임
"""
import argparse, glob, os, sys
import numpy as np
from PIL import Image

CAMS = ('e', 'n', 'w', 's')
BG = 720          # RGB 합이 이 값 이상이면 흰 배경
# 실제 이미지로 보정한 값: hf_grid에 가린 프레임 0.069~0.083, 정상 0.294~1.136.
# 직선 길이 지표는 정상(0.72~0.90)과 가림(0.44~1.00)이 겹쳐 변별력이 없어 참고만 한다.
CURVE_MIN = 0.18  # 휨 비율이 이보다 작으면 인공 절단 의심
MIN_PIX = 200     # 물 픽셀이 이보다 적으면 빈 프레임


def measure(path):
    a = np.asarray(Image.open(path).convert('RGB')).astype(int)
    ink = a.sum(2) < BG
    n = int(ink.sum())
    if n < MIN_PIX:
        return dict(n=n, empty=True)
    ys, xs = np.nonzero(ink)
    x0, x1 = xs.min(), xs.max()
    tops = np.array([np.nonzero(ink[:, x])[0].min() if ink[:, x].any() else -1
                     for x in range(x0, x1 + 1)])
    tops = tops[tops >= 0]
    w = max(len(tops), 1)
    curve = (tops.max() - tops.min()) / w
    # 같은 높이(±1px)가 이어지는 최대 길이
    best = run = 1
    for k in range(1, len(tops)):
        run = run + 1 if abs(int(tops[k]) - int(tops[k - 1])) <= 1 else 1
        best = max(best, run)
    return dict(n=n, empty=False, w=int(w), h=int(ys.max() - ys.min()),
                curve=float(curve), flat=float(best / w),
                edge=(int(ink[0, :].sum()), int(ink[-1, :].sum()),
                      int(ink[:, 0].sum()), int(ink[:, -1].sum())),
                top=int(tops.min()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('root')
    ap.add_argument('--cams', default='e,n,w,s')
    a = ap.parse_args()
    cams = [c for c in a.cams.split(',') if c in CAMS]
    bad_edge, bad_flat, bad_empty = [], [], []
    tot = 0
    stats = {}
    for c in cams:
        files = sorted(glob.glob(os.path.join(a.root, f'{c}_*.png')))
        cs = []
        for p in files:
            tot += 1
            m = measure(p)
            name = os.path.basename(p)
            if m['empty']:
                bad_empty.append((name, m['n'])); continue
            if any(m['edge']):
                bad_edge.append((name, m['edge']))
            if m['curve'] < CURVE_MIN:
                bad_flat.append((name, m['curve'], m['flat'], m['top']))
            cs.append((m['curve'], m['flat']))
        if cs:
            cs = np.array(cs)
            stats[c] = (len(files), cs[:, 0].min(), cs[:, 0].mean(), cs[:, 1].max())
    print(f"검사 {tot}장  ({a.root})")
    print(f"{'방향':>4} {'장수':>5} {'휨 최소':>8} {'휨 평균':>8} {'직선 최대':>9}")
    for c, (n, cmin, cmean, fmax) in stats.items():
        print(f"{c:>4} {n:5d} {cmin:8.3f} {cmean:8.3f} {fmax:9.3f}")
    print(f"\n[1] 화면 밖(경계 접촉): {len(bad_edge)}장")
    for n, e in bad_edge[:10]:
        print(f"    {n} 상{e[0]} 하{e[1]} 좌{e[2]} 우{e[3]}")
    print(f"[2] 인공 절단 의심(윗변 휨 < {CURVE_MIN}): {len(bad_flat)}장")
    for n, cv, fl, tp in bad_flat[:15]:
        print(f"    {n} 휨 {cv:.3f} 직선 {fl:.3f} 상단y {tp}")
    print(f"[3] 빈 프레임: {len(bad_empty)}장")
    for n, k in bad_empty[:10]:
        print(f"    {n} 물픽셀 {k}")
    ok = not (bad_edge or bad_flat or bad_empty)
    print("\n총평: " + ("모두 정상" if ok else "확인 필요"))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
