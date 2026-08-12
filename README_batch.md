# 대량 생성 파이프라인

궤적 1000개를 만들고, 각각 시뮬 → 라벨 → 렌더까지 자동 처리합니다.

## 준비

1. mantaflow 빌드 (메인 README 참고)
2. Genesis 환경 (`cup-fluid-genesis`) — 궤적 생성용
3. mantaflow용 환경 (`fluid`, python 3.10 + numpy)
4. 파일 배치

        mkdir -p /data/$USER/water_cup/logs
        cp water_scene_final.blend /data/$USER/water_cup/
        cp scripts/{height_field_tool,render_gen,extract_gen,make_traj}.py /data/$USER/water_cup/
        cp scenes/cup_idp_gen.py /data/$USER/mantaflow/scenes/
        cp traj/params.csv /data/$USER/water_cup/batch/

## 실행

    sbatch --array=1-1000%2 slurm/traj_job.sh     # 궤적 (GPU 2개)
    sbatch --array=1-1000%2 slurm/batch_job.sh    # 시뮬+라벨+렌더 (GPU 2개)
    squeue -u $USER

궤적이 시뮬보다 5배 빠르므로 동시에 던져도 됩니다. 특정 인덱스만 다시 돌리려면
`--array=17,42,103` 처럼 지정하세요.

## 궤적 구성

인덱스마다 유형과 파라미터가 고정 시드로 결정됩니다(`traj/params.csv`).

| 유형 | 동작 | 수면 형태 |
|---|---|---|
| curve | 곡선 이동, 곡률 증가 | 바깥쪽으로 기움 |
| stop | 직선 가속 후 정지 | 정지 순간 앞으로 쏠림 |
| shake | 제자리 좌우 진동 | 주기적 출렁임 |
| zigzag | 좌우로 흔들며 전진 | 좌우 교대 |
| tilt | 이동하며 기울임(6~14도) | 한쪽으로 지속 기움 |

수위는 55 / 65 / 75 / 85mm 중 무작위, 궤적 길이는 100프레임(0.8초)입니다.
출발 위치와 들어올리기 동작은 모든 궤적이 동일합니다.

## 결과 구조

    /data/$USER/water_cup/out/
      0001/
        height/height_0000.npy ... height_0099.npy   # 32x32 float, 단위 m
        img_0000.png ... img_0099.png                # Camera_e, 1200x720
      0002/
        ...

메시(`sim_XXXX/`)는 라벨·렌더가 끝나면 자동 삭제됩니다.

## 비용

| 단계 | 개당 | 1000개 (GPU 2개) |
|---|---|---|
| 궤적 | 5분 | 42시간 |
| 시뮬 | 8분 (정착 캐시 사용 시) | 67시간 |
| 라벨 | 1분 | 8시간 |
| 렌더 | 12분 | 100시간 |

총 용량 약 40GB (PNG 100장 × 1000).

## 정착 캐시

수위별로 물이 자리잡은 상태를 `~/water_cup/settle_cache/`에 저장해 재사용합니다.
첫 실행 때 수위 4종에 대해 한 번씩 계산되고(각 3~4분), 이후에는 건너뜁니다.
컵 크기나 격자를 바꾸면 캐시를 지우세요.

## 주의

- GPU 할당이 사용자당 제한되는 환경에서는 `%N`으로 동시 실행 수를 맞추세요.
- 마스터 노드에서 계산을 돌리지 마세요.
- 중간에 끊긴 인덱스는 `out/XXXX/`에 파일 수가 부족한 것으로 찾을 수 있습니다.
