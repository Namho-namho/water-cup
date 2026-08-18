#!/bin/bash
# ariel 에서 궤적 여러 개를 노드에 나눠 던진다.
#
#   slurm/submit_ariel.sh 1 6 12 18          # 정착 캐시 만들기(수위 4종)
#   slurm/submit_ariel.sh $(seq 2 5) $(seq 7 11)
#
# 왜 이런 방식인가
#   - 제출 검사 플러그인이 --gres=gpu:1 을 그냥 못 쓰게 한다. -x/--exclude 는 전부
#     거부되고 -w 로 노드 하나를 지정해야만 통과한다. 그래서 인덱스를 노드에
#     돌아가며 배정하고, 노드마다 배열을 하나씩 던진다(%1 = 노드당 1개씩 순차).
#   - QOS 한도: 큐에 최대 20개, 동시 실행 10개, GPU 4개. GPU 4개가 실질 상한이라
#     기본 노드 수를 4개로 잡는다.
#
# 환경변수
#   NODES  쓸 노드 목록 (기본: 지금 비어 있는 g/v 노드에서 4개 자동 선택)
#   MAXQ   큐에 넣을 최대 잡 수 (기본 20)
set -u
W=/nas2/data/$USER/water_cup
JOB=${JOB:-$W/batch_job_ariel.sh}
MAXQ=${MAXQ:-20}
[ $# -gt 0 ] || { echo "사용법: $0 <인덱스...>"; exit 1; }

# 쓸 노드 고르기: high_perf(k,m,n)는 QOS 상 못 쓴다. g/v 중에서 고른다.
if [ -z "${NODES:-}" ]; then
  NODES=$(sinfo -h -p batch_grad -N -o "%N %T" \
          | awk '$2=="idle" || $2=="mixed" {print $1}' \
          | grep -E "ariel-(g|v)" | sort -u | head -4 | paste -sd,)
fi
[ -n "$NODES" ] || { echo "쓸 수 있는 g/v 노드를 못 찾았다"; exit 1; }
IFS=',' read -ra ND <<< "$NODES"
echo "노드 ${#ND[@]}개: $NODES"

# 큐 여유 확인
# -r 없이 세면 대기 중인 배열이 한 줄로 접혀 과소 계산된다. 반드시 -r 로 센다.
Q=$(squeue -u $USER -h -r | wc -l)
N=$#
if [ $((Q + N)) -gt $MAXQ ]; then
  echo "큐에 $Q 개가 있고 $N 개를 더 넣으면 한도($MAXQ)를 넘는다."
  echo "  나눠서 던지거나 (squeue -u $USER | wc -l) 이 줄어든 뒤 다시 실행하라."
  exit 1
fi

# 인덱스를 노드에 돌아가며 배정
declare -A LIST
k=0
for i in "$@"; do
  n=${ND[$((k % ${#ND[@]}))]}
  LIST[$n]="${LIST[$n]:-},$i"
  k=$((k+1))
done
for n in "${!LIST[@]}"; do
  A=${LIST[$n]#,}
  echo -n "  $n <- $A  : "
  sbatch -w "$n" --array="$A%1" "$JOB" 2>&1 | tail -1
done
echo
squeue -u $USER -o "%.14i %.10P %.8T %.20R %.30N" | head -12
