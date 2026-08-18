#!/bin/bash
# 진행 상황 한 줄 요약
W=/nas2/data/$USER/water_cup
D=""; P=""
for i in $(seq -w 1 25); do
  n=$(ls $W/out/00$i/*.png 2>/dev/null | wc -l)
  m=$(ls $W/out/00$i/height_*/*.npy 2>/dev/null | wc -l)
  if [ "$n" -gt 0 ] && [ "$n" -eq "$m" ]; then D="$D $i"
  elif [ "$n" -gt 0 ] || [ "$m" -gt 0 ]; then P="$P $i"; fi
done
R=$(squeue -u $USER -h -t RUNNING -o "%K@%N" | paste -sd" ")
Q=$(squeue -u $USER -h -t PENDING -o "%K" | paste -sd" ")
echo "완료 $(echo $D | wc -w)/25 [$D ] | 진행중 ${R:-없음} | 대기 ${Q:-없음} | $(date +%H:%M)"
