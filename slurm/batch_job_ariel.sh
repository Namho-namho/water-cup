#!/bin/bash
# ariel(세라프 새 계정)용 배치 잡. moana 용 batch_job.sh 와 다른 점:
#   - 작업 경로가 /data/$USER 가 아니라 /nas2/data/$USER
#   - conda 가 anaconda3 가 아니라 miniconda3
#   - 파티션이 batch_grad
#   - 제출 검사 플러그인 때문에 실행 노드를 -w 로 지정해야 한다.
#     이 파일에는 노드를 박지 않고 submit_ariel.sh 가 sbatch -w 로 넘긴다.
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-gpu=8
#SBATCH --mem-per-gpu=64G
#SBATCH -p batch_grad
#SBATCH -o /nas2/data/%u/water_cup/logs/sim_%A_%a.log
#SBATCH --time=8:00:00

I=$(printf %04d $SLURM_ARRAY_TASK_ID)
W=/nas2/data/$USER/water_cup
B=$W/batch
SCENE=/nas2/data/$USER/mantaflow/scenes/cup_idp_gen.py
BLENDER=/nas2/data/$USER/blender-4.5.3-linux-x64/blender

source /nas2/data/$USER/miniconda3/etc/profile.d/conda.sh
conda activate fluid

# params.csv에서 수위 읽기
WL=$(awk -F, -v i=$SLURM_ARRAY_TASK_ID 'NR>1 && $1==i {print $3}' $B/params.csv)
[ -z "$WL" ] && { echo "params 없음: $I"; exit 1; }

# 인덱스 전용 씬 복사본
S=$B/scene_$I.py
sed -e "s|^TRAJ_FILE.*|TRAJ_FILE    = '$B/traj_$I.txt'|" \
    -e "s|^OUT_DIR.*|OUT_DIR      = '$W/sim_$I'|" \
    -e "s|^WATER_LEVEL.*|WATER_LEVEL  = $WL|" $SCENE > $S

cd /nas2/data/$USER/mantaflow/build
./manta $S || exit 1

# 라벨 + 렌더 (4방향). 라벨 격자가 카메라 방위각을 따르므로 방향마다 같이 뽑는다.
for C in e n w s; do
  # 라벨 -> out/$I/height_$C/height_XXXX.npy
  MESH_DIR=$W/sim_$I CAM_NAME=Camera_$C OUT_LABELS=$W/out/$I/height_$C \
    $BLENDER -b $W/water_scene_final.blend \
    --python $W/extract_gen.py || exit 1
  # Blender는 파이썬이 예외로 죽어도 0을 돌려준다. 결과가 실제로 나왔는지 본다.
  N=$(ls $W/out/$I/height_$C/height_*.npy 2>/dev/null | wc -l)
  [ "$N" -gt 0 ] || { echo "[fail] 라벨 0개: $I $C — 메시를 남겨두고 중단"; exit 1; }

  # 렌더 -> out/$I/${C}_XXXX.png (학습용: 컵 숨김 + 흰 배경 + 컵 밖 물 제거)
  MESH_DIR=$W/sim_$I CAM_NAME=Camera_$C IMG_MODE=1 WATER_ONLY=1 OUT_VIDEO=$W/out/$I/${C}_ \
    $BLENDER -b $W/water_scene_final.blend \
    --python $W/render_gen.py -a || exit 1
done

# 메시 삭제 (용량 절약)
rm -rf $W/sim_$I $S
echo "[done] $I"
