#!/bin/bash
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-gpu=8
#SBATCH --mem-per-gpu=32G
#SBATCH -p batch_ce_ugrad
#SBATCH -o /data/%u/water_cup/logs/traj_%A_%a.log
#SBATCH --time=2:00:00

source /data/$USER/anaconda3/etc/profile.d/conda.sh
conda activate cup-fluid-genesis
cd /data/$USER/cup_fluid_genesis
python /data/$USER/water-cup/scripts/gen_traj_batch.py $SLURM_ARRAY_TASK_ID
