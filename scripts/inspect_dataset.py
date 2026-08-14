#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""water_cup 배치 산출물 검사기.

사용법:
    python3 scripts/inspect_dataset.py [--root water_cup] [--csv-dir report/]

검사 항목
  1. 데이터 완결성 : 궤적별 라벨/이미지 개수, 4방향 유무, 중단 지점
  2. 라벨 이상치   : 유효 셀 수, 음수/컵높이 초과, 프레임 간 점프, NaN 급증
  3. 궤적별 물 거동 : 프레임별 평균 수위 / 기울기 폭, 초기 대비 낙차
  4. params.csv 대조 : 유형별·수위별 문제 빈도, 가속 궤적 비교
  5. 이미지        : 파일 크기 이상치, 4방향 결측
  6. 정착 캐시 정합 : logs/sim_NN.log 을 읽어 settle_cache 재사용 오정렬을 잡는다
  7. 권고          : 궤적별 채택/폐기/절단 구간
"""

import argparse
import csv
import os
import re
import sys
from collections import defaultdict

import numpy as np

# ---- 규격 (CLAUDE.md 및 height_field_tool.py와 일치) ----
GRID_N = 32
VALID_CELLS = 616        # 반경 27mm 안에 들어오는 32x32 셀 수
CUP_HEIGHT = 0.100       # 컵 전체 높이
RIM_H = 0.094            # 컵 테두리까지의 안쪽 높이. 넘으면 넘침
RIM_MAX = 0.104          # 추출기가 채택하는 교점 상한
SAMPLE_FILL = 5.0e-3     # 입자 샘플링으로 인한 실제-설정 수위 차 하한
SAMPLE_FILL_HI = 7.0e-3  # 상한
TILT_WARN = 0.020        # 기울기 폭 경고 기준 20mm
JUMP_WARN = 0.010        # 프레임 간 평균 수위 점프 경고 기준 10mm
CAMS = ("e", "n", "w", "s")
CELL_MM = 2.42           # 격자 셀 크기
CUP_INNER_D_MM = 56.0    # 컵 안지름. 정착 캐시 오정렬이 이보다 크면 물이 컵 밖에서 시작한다
ALIGN_TOL_MM = 5.0       # 이 이하면 사실상 같은 시작 위치로 본다


def circle_mask():
    """추출기와 동일한 규칙으로 유효 셀 마스크를 만든다."""
    xs = np.linspace(-0.030, 0.030, GRID_N)
    dx, dy = np.meshgrid(xs, xs, indexing="ij")
    return dx * dx + dy * dy <= 0.027 ** 2


MASK = circle_mask()


def scan_sim_logs(logdir):
    """시뮬 로그에서 컵 시작 위치와 정착 캐시 사용 방식을 뽑는다.

    정착 캐시는 수위와 격자 크기로만 이름이 정해지는데(w65_g152.uni) 안에 든
    입자 좌표는 캐시를 만든 궤적의 컵 시작 위치에 묶여 있다. 시작 위치가 다른
    궤적이 이 캐시를 읽으면 물이 컵 밖에서 시작한다.
    """
    out = {}
    if not os.path.isdir(logdir):
        return out
    for n in sorted(os.listdir(logdir)):
        m = re.match(r"sim_(\d+)\.log$", n)
        if not m:
            continue
        head = open(os.path.join(logdir, n), errors="ignore").read(65536)
        pos = re.search(r"cup start\s*:\s*x=([\d.eE+-]+) y=([\d.eE+-]+) z=([\d.eE+-]+)", head)
        wat = re.search(r"water\s*:\s*([\d.]+) mm", head)
        if not (pos and wat):
            continue
        out[int(m.group(1))] = {
            "x": float(pos.group(1)), "y": float(pos.group(2)), "z": float(pos.group(3)),
            "water": wat.group(1),
            "mode": "WRITE" if "캐시 없음" in head else "READ",
            "traceback": "Traceback (most recent call last)" in
                         open(os.path.join(logdir, n), errors="ignore").read(),
        }
    return out


def settle_alignment(siminfo):
    """궤적별 정착 캐시 오정렬량(mm)을 계산한다.

    같은 수위의 WRITE 중 가장 나중 것이 최종 캐시 내용이라고 본다(잡이 순차 실행).
    """
    last_writer = {}
    for i in sorted(siminfo):
        if siminfo[i]["mode"] == "WRITE":
            last_writer[siminfo[i]["water"]] = i
    res = {}
    for i, d in siminfo.items():
        ref = last_writer.get(d["water"])
        if ref is None:
            continue
        dx = d["x"] - siminfo[ref]["x"]
        dz = d["z"] - siminfo[ref]["z"]
        res[i] = {
            "ref": ref,
            "offset_mm": ((dx * dx + dz * dz) ** 0.5) * CELL_MM,
            "mode": d["mode"],
            "traceback": d["traceback"],
        }
    return res


def load_params(path):
    rows = {}
    if not os.path.exists(path):
        return rows
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows[int(r["idx"])] = r
    return rows


def frame_index(name, prefix):
    """height_0007.npy -> 7"""
    stem = os.path.splitext(name)[0]
    return int(stem[len(prefix):])


def scan_labels(hdir):
    """라벨 디렉터리를 읽어 프레임별 통계 배열을 만든다."""
    if not os.path.isdir(hdir):
        return [], []
    names = sorted(n for n in os.listdir(hdir) if n.startswith("height_") and n.endswith(".npy"))
    idxs, stats = [], []
    for n in names:
        a = np.load(os.path.join(hdir, n))
        v = a[~np.isnan(a)]
        inside = a[MASK]
        rec = {
            "shape_ok": a.shape == (GRID_N, GRID_N),
            "valid": int(v.size),
            "nan_in_mask": int(np.isnan(inside).sum()),
            "outside_nonnan": int(np.count_nonzero(~np.isnan(a[~MASK]))),
            "mean": float(v.mean()) if v.size else float("nan"),
            "min": float(v.min()) if v.size else float("nan"),
            "max": float(v.max()) if v.size else float("nan"),
            "spread": float(v.max() - v.min()) if v.size else float("nan"),
            "neg": int((v < 0).sum()),
            "over_cup": int((v > CUP_HEIGHT).sum()),
            "over_rim": int((v > RIM_H).sum()),
        }
        idxs.append(frame_index(n, "height_"))
        stats.append(rec)
    return idxs, stats


def scan_images(tdir):
    """카메라별 프레임 목록과 파일 크기를 모은다."""
    out = {}
    if not os.path.isdir(tdir):
        return out
    per = defaultdict(dict)
    for n in os.listdir(tdir):
        if not n.endswith(".png") or "_" not in n:
            continue
        cam = n.split("_", 1)[0]
        if cam not in CAMS:
            continue
        try:
            fi = frame_index(n, cam + "_")
        except ValueError:
            continue
        per[cam][fi] = os.path.getsize(os.path.join(tdir, n))
    for cam in CAMS:
        out[cam] = per.get(cam, {})
    return out


def contiguous_runs(sorted_idx):
    """[0,1,2,5,6] -> [(0,2),(5,6)]"""
    runs = []
    for i in sorted_idx:
        if runs and i == runs[-1][1] + 1:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    return [tuple(r) for r in runs]


def analyze(root, csv_dir=None):
    out_root = os.path.join(root, "out")
    params = load_params(os.path.join(root, "batch", "params.csv"))
    traj_ids = sorted(d for d in os.listdir(out_root)
                      if os.path.isdir(os.path.join(out_root, d)) and d.isdigit())

    report = []
    per_frame_rows = []

    for tid in traj_ids:
        tdir = os.path.join(out_root, tid)
        idx = int(tid)
        p = params.get(idx, {})
        water = float(p.get("water") or "nan")

        lidx, lstats = scan_labels(os.path.join(tdir, "height"))
        imgs = scan_images(tdir)
        n_img = max((len(v) for v in imgs.values()), default=0)

        # 궤적 파일의 프레임 수 = 기대 프레임 수
        tpath = os.path.join(root, "batch", "traj_%04d.txt" % idx)
        n_traj = sum(1 for _ in open(tpath)) if os.path.exists(tpath) else None

        rec = {
            "idx": idx,
            "kind": p.get("kind", "?"),
            "water_mm": water * 1000 if water == water else float("nan"),
            "n_traj": n_traj,
            "n_label": len(lidx),
            "n_img": n_img,
            "img_counts": {c: len(v) for c, v in imgs.items()},
            "label_runs": contiguous_runs(lidx),
        }

        # ---- 이미지 크기 이상치 ----
        sizes = [s for v in imgs.values() for s in v.values()]
        if sizes:
            arr = np.array(sizes, dtype=float)
            med = float(np.median(arr))
            rec["img_size_med"] = med
            rec["img_size_min"] = float(arr.min())
            rec["img_size_max"] = float(arr.max())
            # 중앙값의 절반 미만 / 2배 초과를 의심 파일로 본다
            bad = [(cam, fi, sz) for cam, v in imgs.items() for fi, sz in sorted(v.items())
                   if sz < med * 0.5 or sz > med * 2.0]
            rec["img_outliers"] = bad
        else:
            rec["img_size_med"] = float("nan")
            rec["img_outliers"] = []

        # 4방향 프레임 집합 불일치
        allf = set()
        for v in imgs.values():
            allf |= set(v)
        rec["img_missing_by_cam"] = {c: sorted(allf - set(imgs[c])) for c in CAMS
                                     if allf - set(imgs[c])}

        # ---- 라벨 이상치 ----
        if lstats:
            means = np.array([s["mean"] for s in lstats])
            spreads = np.array([s["spread"] for s in lstats])
            valids = np.array([s["valid"] for s in lstats])
            rec["mean_first"] = float(means[0])
            rec["mean_last"] = float(means[-1])
            rec["mean_min"] = float(np.nanmin(means))
            rec["mean_mean"] = float(np.nanmean(means))
            rec["spread_max"] = float(np.nanmax(spreads))
            rec["spread_mean"] = float(np.nanmean(spreads))
            rec["n_tilt_over"] = int(np.nansum(spreads > TILT_WARN))
            rec["n_valid_bad"] = int((valids != VALID_CELLS).sum())
            rec["valid_min"] = int(valids.min())
            rec["n_neg"] = int(sum(s["neg"] for s in lstats))
            rec["n_over_cup"] = int(sum(1 for s in lstats if s["over_cup"]))
            rec["n_over_rim"] = int(sum(1 for s in lstats if s["over_rim"]))
            rec["n_outside_nonnan"] = int(sum(1 for s in lstats if s["outside_nonnan"]))
            rec["n_shape_bad"] = int(sum(1 for s in lstats if not s["shape_ok"]))

            d = np.abs(np.diff(means))
            rec["n_jump"] = int(np.nansum(d > JUMP_WARN))
            rec["jump_max"] = float(np.nanmax(d)) if d.size else 0.0
            rec["jump_frames"] = [int(lidx[i + 1]) for i in np.where(d > JUMP_WARN)[0]]

            # 초기 대비 낙차 (설정 수위 + 샘플링 오프셋을 기준으로)
            if water == water:
                rec["fill_offset"] = float(means[0] - water)
                rec["drop_mm"] = float((means[0] - np.nanmin(means)) * 1000)
                rec["end_drop_mm"] = float((means[0] - means[-1]) * 1000)

            # 유효 셀이 616이 아닌 프레임 구간
            badf = [int(lidx[i]) for i in np.where(valids != VALID_CELLS)[0]]
            rec["valid_bad_frames"] = badf
            rec["valid_bad_runs"] = contiguous_runs(sorted(badf))
            rec["valid_first"] = int(valids[0])

            # 라벨 결함 = 유효셀 결손(광선이 수면을 못 찾음) 또는 컵 높이 초과(물방울 오독).
            # 기울기 폭이 큰 것 자체는 결함이 아니라 실제 급경사일 수 있어 따로 센다.
            defect = [(valids[k] != VALID_CELLS or lstats[k]["over_cup"] > 0)
                      for k in range(len(lidx))]
            rec["n_defect"] = int(sum(defect))
            rec["defect_runs"] = contiguous_runs([lidx[k] for k, b in enumerate(defect) if b])
            safe = -1
            for k, fi in enumerate(lidx):
                if defect[k]:
                    break
                safe = fi
            rec["safe_until"] = safe

            for k, fi in enumerate(lidx):
                s = lstats[k]
                per_frame_rows.append({
                    "idx": idx, "kind": rec["kind"], "water_mm": rec["water_mm"],
                    "frame": fi, "valid": s["valid"],
                    "mean_mm": s["mean"] * 1000, "min_mm": s["min"] * 1000,
                    "max_mm": s["max"] * 1000, "spread_mm": s["spread"] * 1000,
                    "neg": s["neg"], "over_cup": s["over_cup"], "over_rim": s["over_rim"],
                })
        report.append(rec)

    if csv_dir:
        os.makedirs(csv_dir, exist_ok=True)
        with open(os.path.join(csv_dir, "per_frame.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(per_frame_rows[0].keys()))
            w.writeheader()
            w.writerows(per_frame_rows)
        keys = ["idx", "kind", "water_mm", "n_traj", "n_label", "n_img",
                "mean_first", "mean_last", "mean_min", "spread_max", "spread_mean",
                "n_tilt_over", "n_valid_bad", "valid_min", "n_jump", "jump_max",
                "n_over_rim", "n_over_cup", "n_neg", "drop_mm", "end_drop_mm"]
        with open(os.path.join(csv_dir, "per_traj.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for r in report:
                w.writerow(r)

    align = settle_alignment(scan_sim_logs(os.path.join(root, "logs")))
    for r in report:
        r["align"] = align.get(r["idx"])
    return report, params


def mm(x):
    return "  n/a" if x != x else "%5.1f" % (x * 1000)


def print_report(report, params):
    print("=" * 100)
    print("1) 데이터 완결성")
    print("=" * 100)
    print("%-4s %-7s %6s %6s %6s %6s   %s" %
          ("idx", "kind", "water", "traj", "label", "img", "비고"))
    broken = []
    for r in report:
        note = []
        if r["n_label"] != r["n_img"]:
            note.append("라벨≠이미지")
            broken.append(r["idx"])
        if r["n_traj"] and r["n_img"] and r["n_img"] != r["n_traj"]:
            note.append("이미지≠궤적(%d)" % r["n_traj"])
        cnts = set(r["img_counts"].values())
        if len(cnts) > 1:
            note.append("4방향 불일치 %s" % r["img_counts"])
        if r["img_missing_by_cam"]:
            note.append("결측 %s" % r["img_missing_by_cam"])
        if len(r["label_runs"]) > 1:
            note.append("라벨 불연속 %s" % (r["label_runs"],))
        print("%-4d %-7s %6.0f %6s %6d %6d   %s" %
              (r["idx"], r["kind"], r["water_mm"], r["n_traj"], r["n_label"],
               r["n_img"], ", ".join(note) if note else "OK"))
    if broken:
        print("\n  >> 라벨이 이미지와 어긋난 궤적: %s" % broken)

    print()
    print("=" * 100)
    print("2) 라벨 이상치  (유효셀 %d 기준)" % VALID_CELLS)
    print("=" * 100)
    print("%-4s %-7s %7s %7s %7s %7s %7s %7s %7s" %
          ("idx", "kind", "유효≠", "최소유효", "음수", ">100mm", ">94mm", "점프", "최대점프"))
    for r in report:
        if r["n_label"] == 0:
            continue
        print("%-4d %-7s %7d %7d %7d %7d %7d %7d %7s" %
              (r["idx"], r["kind"], r.get("n_valid_bad", 0), r.get("valid_min", 0),
               r.get("n_neg", 0), r.get("n_over_cup", 0), r.get("n_over_rim", 0),
               r.get("n_jump", 0), mm(r.get("jump_max", float("nan")))))
    for r in report:
        if r.get("valid_bad_runs"):
            print("  #%02d 유효셀 결손 구간: %s" %
                  (r["idx"], ", ".join("%d-%d" % x for x in r["valid_bad_runs"])))
        if r.get("jump_frames"):
            print("  #%02d 평균수위 급변 프레임: %s" % (r["idx"], r["jump_frames"]))

    print()
    print("=" * 100)
    print("3) 궤적별 물 거동  (단위 mm, 컵 안바닥 기준)")
    print("=" * 100)
    print("%-4s %-7s %6s %8s %8s %8s %8s %8s %8s %6s" %
          ("idx", "kind", "설정", "첫프레임", "평균", "최종", "최저", "폭평균", "폭최대", "폭>20"))
    for r in report:
        if r["n_label"] == 0:
            print("%-4d %-7s %6.0f   %s" % (r["idx"], r["kind"], r["water_mm"], "라벨 없음"))
            continue
        print("%-4d %-7s %6.0f %8s %8s %8s %8s %8s %8s %6d" %
              (r["idx"], r["kind"], r["water_mm"],
               mm(r["mean_first"]), mm(r["mean_mean"]), mm(r["mean_last"]),
               mm(r["mean_min"]), mm(r["spread_mean"]), mm(r["spread_max"]),
               r["n_tilt_over"]))

    print()
    print("=" * 100)
    print("4) params.csv 대조")
    print("=" * 100)
    by_kind = defaultdict(list)
    by_water = defaultdict(list)
    for r in report:
        by_kind[r["kind"]].append(r)
        by_water[r["water_mm"]].append(r)

    def agg(name, group):
        ok = [r for r in group if r["n_label"] > 1]
        n_dead = sum(1 for r in group if r["n_label"] <= 1)
        sp = np.mean([r["spread_max"] for r in ok]) if ok else float("nan")
        vb = np.mean([r["n_valid_bad"] for r in ok]) if ok else float("nan")
        tl = np.mean([r["n_tilt_over"] for r in ok]) if ok else float("nan")
        print("%-10s n=%2d  라벨실패=%d  폭최대평균=%s  유효셀결손평균=%5.1f  폭>20평균=%5.1f"
              % (name, len(group), n_dead, mm(sp), vb, tl))

    print("[유형별]")
    for k in sorted(by_kind):
        agg(k, by_kind[k])
    print("[수위별]")
    for k in sorted(by_water):
        agg("%.0fmm" % k, by_water[k])

    accel = [4, 10, 16, 22]
    print("\n[가속도 큰 궤적 %s vs 나머지]" % accel)
    for tag, sel in (("지목", accel), ("나머지", [r["idx"] for r in report if r["idx"] not in accel])):
        g = [r for r in report if r["idx"] in sel and r["n_label"] > 1]
        if not g:
            print("  %s: 비교 가능한 라벨 없음" % tag)
            continue
        print("  %-6s n=%2d  폭최대평균=%s  폭>20평균=%5.1f  유효셀결손평균=%5.1f" %
              (tag, len(g), mm(np.mean([r["spread_max"] for r in g])),
               np.mean([r["n_tilt_over"] for r in g]),
               np.mean([r["n_valid_bad"] for r in g])))

    print()
    print("=" * 100)
    print("5) 이미지")
    print("=" * 100)
    print("%-4s %10s %10s %10s   %s" % ("idx", "중앙값KB", "최소KB", "최대KB", "의심파일"))
    for r in report:
        if r["img_size_med"] != r["img_size_med"]:
            print("%-4d  이미지 없음" % r["idx"])
            continue
        out = r["img_outliers"]
        s = "없음" if not out else "%d개 %s" % (
            len(out), ", ".join("%s_%04d(%.0fKB)" % (c, f, z / 1024) for c, f, z in out[:5]))
        print("%-4d %10.0f %10.0f %10.0f   %s" %
              (r["idx"], r["img_size_med"] / 1024, r["img_size_min"] / 1024,
               r["img_size_max"] / 1024, s))


def print_diagnosis(report):
    print()
    print("=" * 100)
    print("6) 정착 캐시 정합성  (컵 안지름 %.0fmm 보다 큰 오정렬이면 물이 컵 밖에서 시작)"
          % CUP_INNER_D_MM)
    print("=" * 100)
    if not any(r.get("align") for r in report):
        print("  logs/ 를 읽을 수 없어 생략")
        return
    print("%-4s %-7s %-6s %8s %10s %10s   %s" %
          ("idx", "kind", "캐시", "기준궤적", "오정렬mm", "f0유효셀", "판정"))
    for r in report:
        a = r.get("align")
        if not a:
            continue
        off = a["offset_mm"]
        v0 = r.get("valid_first", 0)
        if a["mode"] == "WRITE" or off <= ALIGN_TOL_MM:
            verdict = "정상"
        elif off >= CUP_INNER_D_MM:
            verdict = "물이 컵 밖 (완전 분리)"
        else:
            verdict = "물이 컵에 일부만 걸침"
        print("%-4d %-7s %-6s %8s %10.1f %10d   %s" %
              (r["idx"], r["kind"], a["mode"], "#%02d" % a["ref"], off, v0, verdict))
    bad = [r["idx"] for r in report
           if r.get("align") and r["align"]["mode"] == "READ"
           and r["align"]["offset_mm"] > ALIGN_TOL_MM]
    if bad:
        print("\n  >> 정착 캐시 오정렬 궤적(시뮬 자체가 무효): %s" % bad)
    tb = [r["idx"] for r in report if r.get("align") and r["align"]["traceback"]]
    if tb:
        print("  >> 라벨 단계가 예외로 중단된 궤적: %s" % tb)


def print_recommendation(report):
    print()
    print("=" * 100)
    print("7) 권고")
    print("=" * 100)
    keep, trim, drop = [], [], []
    for r in report:
        a = r.get("align")
        misaligned = a and a["mode"] == "READ" and a["offset_mm"] > ALIGN_TOL_MM
        if misaligned:
            drop.append((r, "정착 캐시 오정렬 %.0fmm — 시뮬/렌더/라벨 모두 무효" % a["offset_mm"]))
        elif r["n_label"] == 0:
            drop.append((r, "라벨 없음"))
        elif r.get("safe_until", -1) < 0:
            drop.append((r, "첫 프레임부터 이상"))
        elif r.get("n_defect", 0) == 0:
            note = "전 구간 정상 (%d프레임)" % r["n_label"]
            if r.get("n_tilt_over", 0):
                note += " — 단 폭>%.0fmm 프레임 %d개(실제 급경사)" % (
                    TILT_WARN * 1000, r["n_tilt_over"])
            keep.append((r, note))
        else:
            trim.append((r, "0~%d 프레임 사용 (전체 %d, 결함 %d프레임, 결함구간 %s)"
                         % (r["safe_until"], r["n_label"], r["n_defect"],
                            ", ".join("%d-%d" % x for x in r["defect_runs"][:4]))))
    for tag, group in (("[그대로 사용]", keep), ("[잘라서 사용]", trim), ("[폐기]", drop)):
        print("\n%s  %d개" % (tag, len(group)))
        for r, why in group:
            print("  #%02d %-7s %3.0fmm  %s" % (r["idx"], r["kind"], r["water_mm"], why))
    usable = sum(r["n_label"] for r, _ in keep) + sum(r["safe_until"] + 1 for r, _ in trim)
    total = sum(r["n_img"] for r in report)
    print("\n  쓸 수 있는 프레임: %d / 렌더된 %d  (%.0f%%)" % (usable, total, 100.0 * usable / total))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="water_cup")
    ap.add_argument("--csv-dir", default=None)
    a = ap.parse_args()
    if not os.path.isdir(os.path.join(a.root, "out")):
        sys.exit("out/ 을 찾을 수 없다: %s" % a.root)
    report, params = analyze(a.root, a.csv_dir)
    print_report(report, params)
    print_diagnosis(report)
    print_recommendation(report)


if __name__ == "__main__":
    main()
