#!/bin/bash
# 세라프에서 완료된 궤적 결과를 로컬 보관 폴더로 받아 검증한다.
#
#   scripts/fetch_traj.sh 5 12 17        # 인덱스 여러 개
#   scripts/fetch_traj.sh $(seq 2 11)
#
# 보관 구조:  ~/water_cup/dataset/XXXX/
#               {e,n,w,s}_0000.png ...            입력 이미지 1280x720
#               height_{e,n,w,s}/height_0000.npy  정답 32x32 float32
#               height_{e,n,w,s}/label_meta.json  라벨 추출 설정
#               info.txt                          궤적 정보
set -u
REMOTE=${REMOTE:-shawnbest@moana.khu.ac.kr}
PORT=${PORT:-30080}
RROOT=${RROOT:-/data/shawnbest/water_cup}
DS=${DS:-$HOME/water_cup/dataset}
REPO=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$DS"
for n in "$@"; do
  I=$(printf %04d "$n")
  # 세라프에서 다 끝났는지 먼저 본다 (렌더 4방향 x 프레임 수)
  R=$(ssh -p $PORT $REMOTE "cd $RROOT/out/$I 2>/dev/null && echo \$(ls *.png 2>/dev/null|wc -l) \$(ls height_*/*.npy 2>/dev/null|wc -l)" 2>/dev/null)
  set -- $R
  if [ -z "${1:-}" ] || [ "${1:-0}" -eq 0 ]; then echo "[$I] 세라프에 결과 없음 - 건너뜀"; continue; fi
  if [ "$1" -ne "$2" ]; then echo "[$I] 아직 진행 중 (png $1, npy $2) - 건너뜀"; continue; fi
  echo "[$I] 받는 중 (png $1, npy $2)"
  mkdir -p "$DS/$I"
  rsync -a -e "ssh -p $PORT" "$REMOTE:$RROOT/out/$I/" "$DS/$I/" || { echo "[$I] 전송 실패"; continue; }
  # 개수·크기 대조
  L=$(cd "$DS/$I" && find . -type f ! -name info.txt -printf "%s %p\n" | sort -k2 | md5sum | cut -d' ' -f1)
  S=$(ssh -p $PORT $REMOTE "cd $RROOT/out/$I && find . -type f -printf '%s %p\n' | sort -k2 | md5sum | cut -d' ' -f1")
  [ "$L" = "$S" ] && echo "[$I] 검증 OK (파일 목록·크기 일치)" || { echo "[$I] 검증 실패!"; continue; }
  # 궤적 정보
  python3 - "$I" "$REPO" "$DS/$I" <<'PY'
import csv, sys, os
import numpy as np
idx, repo, out = int(sys.argv[1]), sys.argv[2], sys.argv[3]
P = {int(r['idx']): r for r in csv.DictReader(open(f'{repo}/traj/batch/params.csv'))}
p = P[idx]
t = np.loadtxt(f'{repo}/traj/batch/traj_{idx:04d}.txt')
v = np.gradient(t[:, :3], 0.008, axis=0); a = np.gradient(v, 0.008, axis=0)
ang = np.degrees(2 * np.arccos(np.clip(np.abs(t[:, 3]), 0, 1)))
hs = sorted(f for f in os.listdir(f'{out}/height_e') if f.endswith('.npy'))
H = [np.load(f'{out}/height_e/{f}') for f in hs]
val = [int((~np.isnan(h)).sum()) for h in H]
mx = [float(np.nanmax(h)) * 1000 for h in H]
sp = [float(np.nanmax(h) - np.nanmin(h)) * 1000 for h in H]
open(f'{out}/info.txt', 'w').write(f"""traj_{idx:04d}
유형        : {p['kind']}
수위        : {float(p['water'])*1000:.0f} mm
프레임 수   : {len(t)}  (이미지 {len(t)}장 x 4방향, 라벨 {len(hs)}개 x 4방향)
최대 속도   : {np.linalg.norm(v,axis=1).max():.2f} m/s
최대 가속도 : {np.linalg.norm(a,axis=1).max():.2f} m/s^2  (설계 예상 {p['acc_pred']})
최대 자세변화: {ang.max():.1f} deg
수면 통계   : 최고 {max(mx):.1f} mm(컵 안바닥 기준), 기울기 폭 {min(sp):.1f}~{max(sp):.1f} mm
테두리 초과 : {sum(1 for h in H if np.nanmax(h) > 0.094)} / {len(H)} 프레임 (94mm 기준)

라벨       : {H[0].shape[0]}x{H[0].shape[1]}, 컵 축에 수직인 평면, 컵 안바닥 기준 축방향 거리
             유효셀 {min(val)}~{max(val)} / 616, 최고 {max(mx):.1f} mm
""")
print(f"[{idx:04d}] info.txt 기록")
PY
done
