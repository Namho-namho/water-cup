#!/bin/bash
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-gpu=8
#SBATCH --mem-per-gpu=64G
#SBATCH -p batch_ce_ugrad
#SBATCH -o /data/%u/water_cup/logs/render_%j.log

MESH=$1; CAM=$2; OUT=$3; S=$4; E=$5
MESH_DIR=$MESH CAM_NAME=$CAM OUT_VIDEO=$OUT F_START=$S F_END=$E \
  /data/$USER/blender-4.5.3-linux-x64/blender -b \
  /data/$USER/water_cup/water_scene_final.blend \
  --python /data/$USER/water_cup/render_gen.py -a
