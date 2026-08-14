#!/usr/bin/env python3
"""문제 프레임의 물 메시가 컵 안에 제대로 들어 있는지 본다. Blender 없이 돈다.

    python3 scripts/debug_frame.py <메시폴더> <궤적프레임번호>
    python3 scripts/debug_frame.py ~/water_cup/sim_0009 0

메시폴더는 meta.json 과 mesh_XXXX.bobj.gz 가 있는 시뮬 출력 폴더다.
궤적 프레임 번호는 라벨 파일 번호(height_XXXX.npy)와 같은 번호다.

출력
  - 컵 자세와 격자 원점(컵 안바닥 중심)
  - 메시 꼭짓점 중 컵 안(안반경 28mm, 안바닥~테두리)에 든 개수
  - 컵 기준 좌표 분포: 축 방향 높이, 축에서의 반경
  - 물 중심이 컵 축에서 얼마나 벗어났는지 (정착 캐시 오정렬 진단)
  - 라벨 샘플 격자(반경 27mm)에서 수직으로 물이 있는 셀 수 추정
"""
import gzip
import json
import os
import struct
import sys

import numpy as np

GRID_N = 32
CUP_INNER_R = 0.030      # 격자 범위 (샘플 반경과 별개)
SAMPLE_R = 0.027


def read_bobj(path):
    """mantaflow bobj.gz 에서 꼭짓점과 삼각형을 읽는다 (extract_gen.py와 같은 규격)."""
    with gzip.open(path, 'rb') as f:
        data = f.read()
    nv = struct.unpack_from('<i', data, 0)[0]
    verts = np.frombuffer(data, dtype=np.float32, count=nv * 3, offset=4).reshape(-1, 3)
    off = 4 + nv * 12
    nn = struct.unpack_from('<i', data, off)[0]
    off += 4 + nn * 12
    nt = struct.unpack_from('<i', data, off)[0]
    off += 4
    tris = np.frombuffer(data, dtype=np.int32, count=nt * 3, offset=off).reshape(-1, 3)
    return verts.astype(np.float64), tris


def quat_matrix(q):
    w, x, y, z = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                     [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                     [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]])


def pct(a, ps=(0, 5, 50, 95, 100)):
    return "  ".join(f"{p}%:{np.percentile(a, p) * 1000:7.1f}" for p in ps)


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    mesh_dir = os.path.expanduser(sys.argv[1])
    i = int(sys.argv[2])

    M = json.load(open(f"{mesh_dir}/meta.json"))
    H = M['H']
    S = float(M['gs'][2])
    GX0, GY0, GZ0 = M['cupCenterX'], M['cupBottom'], M['cupCenterZ']
    CEN = np.array([M['gs'][0] / 2, M['gs'][1] / 2, M['gs'][2] / 2])
    inner_r = M['cup_inner_r']
    cup_h = M['cup_height']
    base_t = M['cup_bottom_t']
    traj = np.loadtxt(os.path.expanduser(M['traj_file']))
    if not (0 <= i < len(traj)):
        sys.exit(f"궤적 프레임 범위 밖: 0~{len(traj)-1}")
    T0 = traj[0]

    sf = int(round(M['SETTLE_T'] + i * M['TFRAME']))
    path = f"{mesh_dir}/mesh_{sf:04d}.bobj.gz"
    print(f"메시폴더 : {mesh_dir}")
    print(f"궤적     : {M['traj_file']}  ({len(traj)}프레임)  수위 설정 {M['water_level']*1000:.0f}mm")
    print(f"프레임   : 궤적 {i} -> 시뮬 {sf} -> {os.path.basename(path)}")
    if not os.path.exists(path):
        sys.exit("  해당 메시 파일이 없다")

    v, _ = read_bobj(path)
    g = v * S + CEN
    # 시뮬 격자 -> 월드 (extract_gen.py / render_gen.py 와 동일한 변환)
    w = np.stack([(g[:, 0] - GX0) * H + T0[0],
                  (g[:, 2] - GZ0) * H + T0[1],
                  (g[:, 1] - GY0) * H + T0[2]], axis=1)

    pose = traj[i][:7]
    cup_pos = pose[:3]
    R = quat_matrix(pose[3:7])
    cup_up = R @ np.array([0.0, 0.0, 1.0])
    base = cup_pos + cup_up * base_t          # 컵 안바닥 중심 = 격자 원점, 높이 0
    tilt = np.degrees(np.arccos(np.clip(cup_up[2], -1, 1)))

    print(f"\n[컵] 위치 {np.round(cup_pos,4)}  기울기 {tilt:.2f}도")
    print(f"     안바닥 중심(격자 원점) {np.round(base,4)}  안반경 {inner_r*1000:.0f}mm "
          f"높이 {cup_h*1000:.0f}mm")

    # 컵 기준 좌표: 축 방향 높이 h, 축에서의 반경 r
    rel = w - base
    h = rel @ cup_up
    radial = rel - np.outer(h, cup_up)
    r = np.linalg.norm(radial, axis=1)

    # 표면 재구성이 입자보다 2~3mm 바깥에 표면을 만들므로 여유를 준다
    band = (h >= -0.002) & (h <= cup_h)
    inside = (r <= inner_r + 0.003) & band
    print(f"\n[메시] 꼭짓점 {len(w)}개 | 컵 안(r<={inner_r*1000:.0f}+3mm, 0~{cup_h*1000:.0f}mm) "
          f"{int(inside.sum())}개 ({100.0*inside.sum()/len(w):.1f}%)"
          f" | 높이 범위만 맞는 것 {int(band.sum())}개")
    print(f"  컵 기준 높이 mm : {pct(h)}")
    print(f"  컵 축 반경  mm : {pct(r)}")
    if inside.any():
        print(f"  컵 안 높이  mm : {pct(h[inside])}")

    c = w.mean(axis=0)
    crel = c - base
    ch = crel @ cup_up
    coff = np.linalg.norm(crel - ch * cup_up)
    print(f"\n[물 중심] 월드 {np.round(c,4)}")
    print(f"  컵 축에서 수평으로 {coff*1000:.1f}mm, 축 방향 높이 {ch*1000:.1f}mm")
    if coff > inner_r:
        print(f"  >> 물 중심이 컵 안반경({inner_r*1000:.0f}mm) 밖이다. "
              "물이 컵에 들어 있지 않은 시뮬이다.")
        print("     정착 캐시(settle_cache/wNN_g152.uni)는 격자 절대 좌표로 저장되는데,"
              " 컵의 격자 배치(cupCenterX/cupBottom/cupCenterZ)는 궤적마다 다르다."
              " 다른 궤적이 만든 캐시를 읽으면 물이 컵 밖에서 시작한다.")
    elif coff > inner_r * 0.5:
        print(f"  >> 물이 컵에 일부만 걸쳐 있다. 라벨을 믿을 수 없다.")

    # 라벨 격자에서 물이 잡히는 셀 추정 (컵 평면 격자, 컵 축 방향 광선)
    xs = np.linspace(-CUP_INNER_R, CUP_INNER_R, GRID_N)
    di, dj = np.meshgrid(xs, xs, indexing='ij')
    disc = (di * di + dj * dj) <= SAMPLE_R ** 2
    # 각 샘플점 주위(셀 반경)에 물 꼭짓점이 있으면 광선이 뭔가 맞을 것으로 본다
    step = xs[1] - xs[0]
    ex = R @ np.array([1.0, 0.0, 0.0])
    ey = R @ np.array([0.0, 1.0, 0.0])
    pu = radial @ ex
    pv = radial @ ey
    sel = (h >= -0.002) & (h <= cup_h)
    hit = np.zeros((GRID_N, GRID_N), dtype=bool)
    if sel.any():
        ai = np.round((pu[sel] - xs[0]) / step).astype(int)
        bi = np.round((pv[sel] - xs[0]) / step).astype(int)
        ok = (ai >= 0) & (ai < GRID_N) & (bi >= 0) & (bi < GRID_N)
        hit[ai[ok], bi[ok]] = True
    print(f"\n[라벨 격자] 샘플 셀 {int(disc.sum())}개 중 물 꼭짓점이 덮는 셀 "
          f"{int((hit & disc).sum())}개")
    print("  (실제 라벨의 유효 셀 수와 정확히 같지는 않다. 물이 어디에 있는지 보는 용도)")


if __name__ == '__main__':
    main()
