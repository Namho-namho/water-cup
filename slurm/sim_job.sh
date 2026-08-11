#!/bin/bash
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-gpu=8
#SBATCH --mem-per-gpu=128G
#SBATCH -p batch_ce_ugrad
#SBATCH --time=24:00:00
#SBATCH -o /data/shawnbest/water_cup/sim_%j.log

source /data/shawnbest/anaconda3/etc/profile.d/conda.sh
conda activate fluid
cd /data/shawnbest/mantaflow/build
./manta ../scenes/cup_idp_gen.py
