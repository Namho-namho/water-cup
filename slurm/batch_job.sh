#!/bin/bash
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-gpu=8
#SBATCH --mem-per-gpu=64G
#SBATCH -p batch_ce_ugrad
#SBATCH -o /data/%u/water_cup/logs/sim_%A_%a.log
#SBATCH --time=4:00:00

I=$(printf %04d $SLURM_ARRAY_TASK_ID)
W=/data/$USER/water_cup
B=$W/batch
SCENE=/data/$USER/mantaflow/scenes/cup_idp_gen.py

source /data/$USER/anaconda3/etc/profile.d/conda.sh
conda activate fluid

# params.csv에서 수위 읽기
WL=$(awk -F, -v i=$SLURM_ARRAY_TASK_ID 'NR>1 && $1==i {print $3}' $B/params.csv)
[ -z "$WL" ] && { echo "params 없음: $I"; exit 1; }

# 인덱스 전용 씬 복사본
S=$B/scene_$I.py
sed -e "s|^TRAJ_FILE.*|TRAJ_FILE    = '$B/traj_$I.txt'|" \
    -e "s|^OUT_DIR.*|OUT_DIR      = '$W/sim_$I'|" \
    -e "s|^WATER_LEVEL.*|WATER_LEVEL  = $WL|" $SCENE > $S

cd /data/$USER/mantaflow/build
./manta $S || exit 1

# 라벨
MESH_DIR=$W/sim_$I OUT_LABELS=$W/out/$I/height \
  /data/$USER/blender-4.5.3-linux-x64/blender -b $W/water_scene_final.blend \
  --python $W/extract_gen.py || exit 1

# 렌더 (PNG, 4방향)
for C in e n w s; do
  MESH_DIR=$W/sim_$I CAM_NAME=Camera_$C IMG_MODE=1 OUT_VIDEO=$W/out/$I/${C}_ \
    /data/$USER/blender-4.5.3-linux-x64/blender -b $W/water_scene_final.blend \
    --python $W/render_gen.py -a || exit 1
done

# 메시 삭제 (용량 절약)
rm -rf $W/sim_$I $S
echo "[done] $I"
