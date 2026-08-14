# 대량 생성 파이프라인

궤적 1000개를 만들고, 각각 시뮬 → 라벨 → 렌더까지 자동 처리합니다.

## 준비

1. mantaflow 빌드 (메인 README 참고)
2. Genesis 환경 (`cup-fluid-genesis`) — 궤적 생성용
3. mantaflow용 환경 (`fluid`, python 3.10 + numpy)
4. 파일 배치

        mkdir -p /data/$USER/water_cup/logs
        cp water_scene_final.blend /data/$USER/water_cup/
        cp scripts/{height_field_tool,render_gen,extract_gen,make_traj,check_labels}.py /data/$USER/water_cup/
        cp scenes/cup_idp_gen.py /data/$USER/mantaflow/scenes/
        mkdir -p /data/$USER/water_cup/batch
        cp traj/batch/*.txt traj/batch/params.csv /data/$USER/water_cup/batch/

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

## 포함된 궤적

`traj/batch/` 에 25개가 들어 있습니다(`traj_0001.txt` ~ `traj_0025.txt`).
Genesis에서 Franka가 실제로 컵을 쥐고 움직인 결과이며, 각 파일은 약 100프레임(0.8초)입니다.
`params.csv` 에 인덱스별 유형과 수위가 기록되어 있고, 배치 잡이 이 파일에서 수위를 읽습니다.

측정값 범위: 최대 속도 0.05~1.03 m/s, 최대 가속도 1.4~15.0 m/s²(평균 6.2).
일부 궤적(4, 10, 16, 22번)은 가속도가 12를 넘어 실제 하드웨어 재현이 어려울 수 있습니다.
학습 데이터로는 무관하지만 실기 검증 때 참고하세요.

## 결과 구조

    /data/$USER/water_cup/out/
      0001/
        e_0000.png ... e_0099.png                       # Camera_e, 1280x720
        height_e/height_0000.npy ... height_0099.npy    # 32x32 float, 단위 m
        n_0000.png ... / height_n/                      # Camera_n
        w_0000.png ... / height_w/                      # Camera_w
        s_0000.png ... / height_s/                      # Camera_s
      0002/
        ...

이미지는 학습용 모드(`WATER_ONLY=1`)로 렌더합니다. 컵과 마커를 숨기고 배경을 흰색으로
깔며, 컵 밖으로 튀어나간 물은 메시에서 지웁니다. 물 재질은 그대로라 반사·굴절·흡수로
수면 모양이 드러납니다. 컵이 보이는 예전 이미지가 필요하면 `WATER_ONLY=0`으로 렌더하세요.

라벨 격자가 카메라 방향을 따르므로 방향마다 이미지와 라벨을 같이 뽑습니다.
격자 평면은 컵 축에 수직인 평면이고, 그 평면 안에서 격자를 몇 도 돌릴지를 카메라
광축이 정합니다. 컵이 자기축으로 돌아도 라벨은 따라 돌지 않습니다.
`height_*/label_meta.json` 에 격자 기준·카메라·프레임별 회전각이 기록됩니다.
마커(`cup_marker_x`)는 렌더에서 숨겨집니다(`SHOW_MARKER=1` 이면 표시).
메시(`sim_XXXX/`)는 라벨·렌더가 끝나면 자동 삭제됩니다.

## 라벨 검증

    python3 scripts/check_labels.py /data/$USER/water_cup/out/0001

유효셀 616개, 네 방향 평균 일치, 네 방향이 서로 회전 관계인지 확인합니다.

## 비용

| 단계 | 개당 | 1000개 (GPU 2개) |
|---|---|---|
| 궤적 | 5분 | 42시간 |
| 시뮬 | 8분 (정착 캐시 사용 시) | 67시간 |
| 라벨 | 4분 (4방향) | 33시간 |
| 렌더 | 12분 | 100시간 |

총 용량 약 40GB (PNG 100장 × 1000).

## 정착 캐시

수위별로 물이 자리잡은 상태를 `~/water_cup/settle_cache/`에 저장해 재사용합니다.
첫 실행 때 수위 4종에 대해 한 번씩 계산되고(각 3~4분), 이후에는 건너뜁니다.
컵 크기나 격자를 바꾸면 캐시를 지우세요.

캐시에는 입자가 격자 절대 좌표로 들어 있고, 컵의 격자 배치는 궤적의 이동 범위에서
계산되므로 궤적마다 다릅니다. 그래서 캐시(`wNN_g152_v2.uni`)와 함께 그 배치를
`wNN_g152_v2.json`에 기록하고, 캐시를 쓰는 잡은 그 배치를 그대로 채택합니다.
채택한 배치로 궤적이 도메인을 벗어나면 캐시를 버리고 자기 정착을 계산합니다
(로그의 `settle :` 줄에 어느 쪽인지, 배치가 얼마나 옮겨졌는지 찍힙니다).
배치 정보가 없는 예전 캐시(`wNN_g152.uni`)는 쓰지 않으므로 지워도 됩니다.

## 주의

- GPU 할당이 사용자당 제한되는 환경에서는 `%N`으로 동시 실행 수를 맞추세요.
- 마스터 노드에서 계산을 돌리지 마세요.
- 중간에 끊긴 인덱스는 `out/XXXX/`에 파일 수가 부족한 것으로 찾을 수 있습니다.
