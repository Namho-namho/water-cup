#!/usr/bin/env python3
"""카메라 기준 높이 필드 라벨 검증.

    python3 scripts/check_labels.py OUT_DIR [옵션]

OUT_DIR 안에 방향별 폴더가 있다고 본다.

    OUT_DIR/height_e/height_0000.npy ...
    OUT_DIR/height_n/...  height_w/  height_s/

검사 항목
  1) 유효 셀 수가 방향·프레임마다 616개인지, NaN 마스크가 방향끼리 같은지
  2) 네 방향 라벨의 평균 높이가 서로 같은지 (같은 물이므로)
  3) 네 방향 라벨이 서로 회전 관계인지
     - rot90 : np.rot90 으로 맞춰보고 남는 오차
     - 정밀  : label_meta.json 의 실제 격자 회전각 차이만큼 겹선형 보간으로 돌려 비교
       (CAM_AZIM=position 처럼 회전각 간격이 정확히 90도가 아닌 설정에서도 검증된다)

옵션
  --frames N     검사할 프레임 수 (기본 전부)
  --tol-mean MM  평균 허용 오차, 기본 0.5mm
  --tol-rot MM   회전 비교 허용 RMS, 기본 0.5mm
  --traj PATH    궤적 파일. 컵 회전각 계산용 (없으면 label_meta.json 것을 쓴다)
  --legacy DIR   컵 기준으로 뽑은 예전 라벨 폴더. 평균만 참고로 출력한다
"""
import argparse
import glob
import json
import os
import sys

import numpy as np

# 라벨 폴더 접두어. heightA_cup=버전 A, heightB_world=버전 B, height=예전 데이터
PREFIX = os.environ.get('LABEL_PREFIX', 'heightA_cup')
DIRS = ['e', 'n', 'w', 's']
EXPECT_VALID = 616      # 버전 A 기준. B는 물의 수평 단면이라 프레임마다 다르다


def load_dir(root, d):
    """height_<d> 폴더에서 {프레임번호: 배열} 과 메타를 읽는다."""
    p = os.path.join(root, f'{PREFIX}_{d}')
    if not os.path.isdir(p):
        return None, None
    fields = {}
    for f in sorted(glob.glob(os.path.join(p, 'height_*.npy'))):
        i = int(os.path.basename(f)[7:11])
        fields[i] = np.load(f)
    mp = os.path.join(p, 'label_meta.json')
    meta = json.load(open(mp)) if os.path.exists(mp) else None
    return fields, meta


def cup_angles(traj_path):
    """프레임별 컵 회전각(도)."""
    t = np.loadtxt(os.path.expanduser(traj_path))
    w = np.clip(np.abs(t[:, 3]), 0.0, 1.0)
    return np.degrees(2.0 * np.arccos(w))


def rotate_field(hf, deg, sample_r, grid_r=0.030):
    """격자 좌표계를 +deg 만큼 돌린 관측을 예측한다.

    hf[a,b] 는 원점에서 xs[a]*i + xs[b]*j 만큼 떨어진 지점의 높이다.
    격자축을 deg 만큼 돌리면 (a,b) 셀이 가리키는 월드 지점이 같은 각도로 돌아가므로,
    원래 필드를 그 지점에서 다시 읽어오면 된다. 격자 밖·NaN 이웃은 NaN.
    """
    n = hf.shape[0]
    xs = np.linspace(-grid_r, grid_r, n)
    step = xs[1] - xs[0]
    th = np.radians(deg)
    u, v = np.meshgrid(xs, xs, indexing='ij')
    su = u * np.cos(th) - v * np.sin(th)
    sv = u * np.sin(th) + v * np.cos(th)
    fa = (su - xs[0]) / step
    fb = (sv - xs[0]) / step
    a0 = np.floor(fa).astype(int)
    b0 = np.floor(fb).astype(int)
    ta = fa - a0
    tb = fb - b0
    ok = (a0 >= 0) & (a0 < n - 1) & (b0 >= 0) & (b0 < n - 1)
    ok &= (su**2 + sv**2) <= sample_r**2
    a0c = np.clip(a0, 0, n - 2)
    b0c = np.clip(b0, 0, n - 2)
    out = (hf[a0c, b0c] * (1 - ta) * (1 - tb) + hf[a0c + 1, b0c] * ta * (1 - tb)
           + hf[a0c, b0c + 1] * (1 - ta) * tb + hf[a0c + 1, b0c + 1] * ta * tb)
    return np.where(ok, out, np.nan)


def rms_mm(a, b):
    """겹치는 유효 셀에서의 RMS 오차(mm)와 셀 수."""
    m = ~np.isnan(a) & ~np.isnan(b)
    if not m.any():
        return float('nan'), 0
    return float(np.sqrt(np.mean((a[m] - b[m])**2)) * 1000.0), int(m.sum())


def best_rot90(a, b):
    """b 를 가장 잘 맞추는 np.rot90 회전수 k 와 그때 RMS(mm)."""
    best = (None, float('inf'), 0)
    for k in range(4):
        r, n = rms_mm(np.rot90(a, k), b)
        if n and r < best[1]:
            best = (k, r, n)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('root')
    ap.add_argument('--frames', type=int, default=0)
    ap.add_argument('--tol-mean', type=float, default=0.5)
    ap.add_argument('--tol-rot', type=float, default=0.5)
    ap.add_argument('--traj', default=None)
    ap.add_argument('--legacy', default=None)
    a = ap.parse_args()

    fields, metas = {}, {}
    for d in DIRS:
        f, m = load_dir(a.root, d)
        if f:
            fields[d], metas[d] = f, m
    if len(fields) < 2:
        sys.exit(f"방향별 라벨 폴더를 못 찾았다: {a.root}/height_{{e,n,w,s}}")
    have = [d for d in DIRS if d in fields]     # 카메라가 실제로 도는 순서
    frames = sorted(set.intersection(*[set(fields[d]) for d in have]))
    if a.frames:
        frames = frames[:a.frames]
    if not frames:
        sys.exit("방향끼리 공통인 프레임이 없다")

    meta0 = next((m for m in metas.values() if m), None)
    sample_r = (meta0.get('sample_r') if meta0 else 0.027) or 9.9
    grid_r = meta0.get('grid_r', 0.030) if meta0 else 0.030
    print(f"폴더 {a.root}")
    print(f"방향 {have}  프레임 {len(frames)}개 ({frames[0]}~{frames[-1]})"
          f"  격자기준 {meta0.get('label_frame') if meta0 else '?'}")

    # 컵 회전각
    tp = a.traj or (meta0.get('traj_file') if meta0 else None)
    ang = None
    if tp and os.path.exists(os.path.expanduser(tp)):
        ang = cup_angles(tp)
        print(f"궤적 {tp}  컵 회전 {ang.min():.1f}~{ang.max():.1f}도")

    # 버전 B는 유효 영역이 물의 수평 단면이라 개수가 프레임마다 다르고,
    # 마스크도 방향끼리 같은 게 아니라 90도 돌아간 관계다.
    ver = (meta0 or {}).get('label_version', 'A')
    isB = (ver == 'B')
    ok_valid = ok_mask = ok_mean = True
    means, worst_mean = {}, (0.0, None)
    vcnt = []
    for i in frames:
        m0 = ~np.isnan(fields[have[0]][i])
        vals = {}
        for k, d in enumerate(have):
            hf = fields[d][i]
            v = ~np.isnan(hf)
            vcnt.append(int(v.sum()))
            if not isB and v.sum() != EXPECT_VALID:
                print(f"  [유효셀] f{i:04d} {d}: {v.sum()}개 (기대 {EXPECT_VALID})")
                ok_valid = False
            # A: 마스크가 그대로 같아야 한다 / B: e 기준으로 k*90도 돌린 것과 같아야 한다
            ref = np.rot90(m0, -k) if isB else m0
            if not np.array_equal(v, ref):
                bad = int(np.count_nonzero(v ^ ref))
                if bad > (0 if not isB else max(4, int(0.01 * v.size))):
                    print(f"  [마스크] f{i:04d} {d}: 기준과 {bad}셀 다름"
                          + (" (90도 회전 기준)" if isB else ""))
                    ok_mask = False
            vals[d] = float(np.nanmean(hf))
        means[i] = vals
        spread = (max(vals.values()) - min(vals.values())) * 1000.0
        if worst_mean[1] is None or spread > worst_mean[0]:
            worst_mean = (spread, i)
        if spread > a.tol_mean:
            ok_mean = False

    print(f"\n[버전] {ver} — {(meta0 or {}).get('basis','?')}")
    if isB:
        print(f"[1] 유효 셀 수 : {min(vcnt)}~{max(vcnt)} (물의 수평 단면, 프레임마다 다름)")
        print("    NaN 마스크(90도 회전 기준) : " + ("OK" if ok_mask else "실패"))
    else:
        print("[1] 유효 셀 수 616 : " + ("OK" if ok_valid else "실패"))
        print("    NaN 마스크 일치 : " + ("OK" if ok_mask else "실패"))
    mm = means[worst_mean[1]]
    print(f"[2] 방향별 평균 최대차 {worst_mean[0]:.3f}mm (f{worst_mean[1]:04d}: "
          + " ".join(f"{d}={mm[d]*1000:.2f}" for d in have) + ")"
          + f"  허용 {a.tol_mean}mm : " + ("OK" if ok_mean else "실패"))

    # ---- 회전 관계 ----
    pairs = [(have[k], have[(k + 1) % len(have)]) for k in range(len(have))]
    if len(have) == 2:
        pairs = [(have[0], have[1])]
    print(f"\n[3] 회전 관계 (인접 방향쌍, 허용 RMS {a.tol_rot}mm)")

    order = frames
    if ang is not None:
        order = sorted(frames, key=lambda i: ang[i] if i < len(ang) else 9e9)
        print(f"    컵 회전이 가장 작은 프레임: f{order[0]:04d} ({ang[order[0]]:.2f}도)")

    ok_rot = True
    first_tag = "컵회전 최소" if ang is not None else "첫 프레임"
    for tag, sel in ((first_tag, order[:1]), ("전체", frames)):
        rows = []
        for A, B in pairs:
            k_all, r90_all, rex_all, dz_all = [], [], [], []
            for i in sel:
                fa, fb = fields[A][i], fields[B][i]
                k, r90, _ = best_rot90(fa, fb)
                k_all.append(k)
                r90_all.append(r90)
                if metas[A] and metas[B]:
                    # 격자 평면 안의 회전각 차이가 두 라벨의 정확한 회전량이다.
                    key = ('grid_angle_deg' if 'grid_angle_deg' in metas[A]
                           else 'azim_deg')
                    za = metas[A][key].get(str(i))
                    zb = metas[B].get(key, {}).get(str(i))
                    if za is not None and zb is not None:
                        dz = (zb - za + 180.0) % 360.0 - 180.0
                        dz_all.append(dz)
                        rex_all.append(
                            rms_mm(rotate_field(fa, dz, sample_r, grid_r), fb)[0])
            rows.append((A, B, k_all, r90_all, rex_all, dz_all))
        print(f"  - {tag} ({len(sel)}프레임)")
        for A, B, k_all, r90, rex, dz in rows:
            ks = sorted({k for k in k_all if k is not None})
            s = (f"    {A}->{B}: rot90 k={ks if len(ks) != 1 else ks[0]} "
                 f"RMS {np.mean(r90):.2f}mm (최대 {np.max(r90):.2f})")
            if dz:
                s += (f" | 회전각차 {np.mean(dz):+.1f}도"
                      f"(90도에서 {np.mean(np.abs(np.abs(dz)-90)):.1f}도 벗어남)"
                      f" 정밀 RMS {np.mean(rex):.2f}mm (최대 {np.max(rex):.2f})")
                if np.max(rex) > a.tol_rot:
                    ok_rot = False
            elif np.max(r90) > a.tol_rot:
                ok_rot = False
            print(s)
    print("    판정: " + ("OK" if ok_rot else "허용치 초과"))

    if a.legacy:
        lg = {int(os.path.basename(f)[7:11]): np.load(f)
              for f in sorted(glob.glob(os.path.join(a.legacy, 'height_*.npy')))}
        com = [i for i in frames if i in lg]
        if com:
            dm = [abs(np.nanmean(lg[i]) - np.nanmean(fields[have[0]][i])) * 1000 for i in com]
            nv = [int((~np.isnan(lg[i])).sum()) for i in com]
            print(f"\n[참고] 예전(컵 기준) 라벨 {a.legacy}: {len(com)}프레임 공통, "
                  f"유효셀 {min(nv)}~{max(nv)}, 평균차 {np.mean(dm):.2f}mm (최대 {max(dm):.2f})")

    allok = ok_valid and ok_mask and ok_mean and ok_rot
    print("\n총평: " + ("모두 통과" if allok else "확인 필요"))
    return 0 if allok else 1


if __name__ == '__main__':
    sys.exit(main())
