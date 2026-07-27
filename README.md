# 이동 컵 유체 시뮬 (mantaflow IDP-APIC)

로봇이 물컵을 옮길 때의 (렌더 이미지, 32x32 수면 높이맵) 쌍을 생성합니다.

## 예시 결과

[예시 영상 (media/example.mp4)](media/example.mp4) — traj_slow225 궤적 + 수위 85mm,
225프레임(1.79초) 실시간 재생. 기동 중반에 물이 테두리를 넘어 흘러넘칩니다.

## 구조

Genesis → 컵 궤적(위치+자세, 8ms 간격) → mantaflow(물 시뮬) → Blender(렌더 + 라벨)

시뮬이 meta.json에 설정을 기록하고 렌더/라벨이 그걸 읽습니다.
궤적을 바꿔도 렌더·라벨 스크립트는 수정할 필요가 없습니다.

Blender FLIP Fluids는 같은 시나리오에서 부피가 -13.9% 사라지지만, IDP 적용판은
넘치지 않는 조건에서 1% 이내입니다.

## 설치

필요: Blender 4.5+, cmake/g++/python3-dev, GPU. (Genesis는 궤적을 새로 만들 때만)

    git clone https://github.com/thunil/mantaflow.git
    cd mantaflow
    cp src/implicitdensityprojection.cpp source/plugin/
    mkdir build && cd build
    cmake .. -DGUI=OFF -DOPENMP=ON
    make -j 20

clampToCupAxis 함수가 추가된 파일입니다. 없으면 씬이 실행되지 않습니다.
cmake에서 Python 버전 오류가 나면 -DPYTHON_VERSION=3.10 을 추가하세요.

파일 배치:

    mkdir -p ~/water_cup
    cp ../water-cup/traj/*.txt ~/water_cup/
    cp ../water-cup/water_scene_final.blend ~/water_cup/
    cp ../water-cup/scripts/{height_field_tool,render_gen,extract_gen,analyze,make_traj}.py ~/water_cup/
    cp ../water-cup/scenes/cup_idp_gen.py <mantaflow>/scenes/

simple_075_tilt_only.py 는 Genesis 환경에서 도는 파일이라 별도로 두세요.

## 실행

### 1) 시뮬 (20~50분, 수위에 따라)

scenes/cup_idp_gen.py 상단 CONFIG를 수정합니다:

    TRAJ_FILE    = '~/water_cup/traj_slow225.txt'
    DT_REAL      = 0.008     # 궤적 프레임 간격(초) — 궤적 생성 설정과 반드시 일치
    WATER_LEVEL  = 0.085     # 초기 수위 (m)
    CUP_OUTER_R  = 0.035
    CUP_INNER_R  = 0.028
    CUP_HEIGHT   = 0.100
    CUP_BOTTOM_T = 0.006
    OUT_DIR      = '~/water_cup/idp_out'
    SETTLE_T     = 40.0      # 물이 자리잡는 시간(프레임)
    MARGIN       = 10.0      # 도메인 여유(격자)

    cd <mantaflow>/build
    ./manta ../scenes/cup_idp_gen.py

시작 시 CONFIG가 출력됩니다. 반복 횟수와 컵 배치는 궤적을 읽고 자동 계산되며,
궤적이 도메인을 벗어나면 assert로 중단됩니다.

기본 설정(WATER_LEVEL 0.085)은 컵을 거의 가득 채운 조건이라 기동 중 물이 넘칩니다
(정착 후 실제 수위 91mm, 테두리 94mm). 넘침이 없는 데이터가 필요하면 0.055~0.070으로
낮추세요. 넘침이 있으면 analyze.py의 부피·누수 지표는 의미를 잃습니다(4절 참고).

결과: OUT_DIR에 mesh_XXXX.bobj.gz 와 meta.json
(메시 파일이 궤적 프레임 수보다 몇 개 많을 수 있습니다. 저장 시각 판정의 여유 때문이며,
 렌더·라벨은 필요한 번호만 골라 읽으므로 무해합니다.)

### 2) 라벨 (2~3분)

    MESH_DIR=~/water_cup/idp_out OUT_LABELS=~/water_cup/heights_out \
      blender -b ~/water_cup/water_scene_final.blend --python ~/water_cup/extract_gen.py

32x32 배열(단위 m), 컵 안바닥 기준 수면 높이, 컵 밖은 NaN, 유효 616셀.

### 3) 렌더 (10~25분)

    MESH_DIR=~/water_cup/idp_out OUT_VIDEO=~/water_cup/render/out \
      blender -b ~/water_cup/water_scene_final.blend --python ~/water_cup/render_gen.py \
      -a -- --cycles-device CUDA

출력: out0000-0224.mp4 (Blender가 프레임 범위를 자동으로 붙임)
fps = 1/DT_REAL 이라 실시간 재생입니다. 물이 튀는 장면이 많으면 렌더가 느려집니다.

### 4) 검증

    python ~/water_cup/analyze.py ~/water_cup/idp_out ~/water_cup/heights_out

부피 / 누수 / 컵밖 / 테두리위 비율과 라벨 통계를 출력합니다.
정상 기준(넘치지 않는 조건): 부피 변화 ±1% 이내, 누수 -3격자 이내.
(누수 열이 음수로 조금 나오는 것은 표면 재구성이 입자보다 바깥에 잡히는 정상 오차입니다.)

넘치는 조건에서는 부피가 +30% 가까이, 누수가 -80격자까지 나올 수 있습니다.
이는 계산이 틀린 것이 아니라, 컵 밖으로 흘러나온 물이 도메인 바닥에 얇게 퍼지면서
표면 재구성이 부피를 과대평가하고 누수 열이 바닥에 고인 물을 재기 때문입니다.
넘침 여부는 '컵밖'과 '테두리위' 열로 판단하세요.

## 새 궤적 만들기 (Genesis)

simple_075_tilt_only.py 상단에서 NO_WATER=True 로 두면 물 없이 빠르게 돕니다.

동작 함수:
- move_lin(위치, 자세, 스텝수, 손가락) — 직선 이동. 스텝수가 속도/가속도를 결정
  (같은 거리에서 스텝수 2배 → 가속도 1/4)
- move_lin_tilt(위치, 스텝수, 손가락, tilt_deg, tilt_period) — 이동하며 손목 좌우 기울기

실행 후 변환:

    python ~/water_cup/make_traj.py ~/water_cup/traj_xxx ~/water_cup/traj_xxx.txt

이동거리·최대속도·최대가속도·자세변화가 출력됩니다.
(주의: make_traj.py는 프레임 간격을 8ms로 가정해 속도/가속도를 계산합니다.
 다른 간격으로 궤적을 만들었다면 그 숫자는 참고용으로만 보세요.)

참고: 이 컵(안지름 56mm, 수위 55mm 기준)의 슬로싱 고유주기는 약 256ms(3.9Hz)입니다.
(수위를 올려도 이미 깊은 물 영역이라 주기는 크게 변하지 않습니다.)
기동 시간이 이 주기의 2~3배면 공진에 가까워 크게 출렁이고,
tilt_period를 64스텝으로 잡으면 공진, 96스텝이면 비공진입니다.

## 궤적 파일 형식

한 줄에 `x y z qw qx qy qz` (위치는 m, world 좌표에서 z가 위).
줄 간격이 CONFIG의 DT_REAL 초입니다.

## 주의사항

**시간축이 조용히 틀어질 수 있음** — 궤적을 다른 설정으로 만들었는데 DT_REAL을 안 바꾸면
에러 없이 시뮬 속도만 달라집니다. Genesis의 DT × RENDER_EVERY 가 궤적 프레임 간격입니다.

**렌더용 컵과 시뮬 컵이 현재 다릅니다** — 시뮬은 내경 28mm·벽 7mm이고,
water_scene_final.blend의 컵 오브젝트는 내경 30mm·벽 1.5mm입니다.
영상에서 물이 실제보다 약간 안쪽에 보입니다. 라벨은 컵 좌표계 기준이라 영향받지 않습니다.
실기와 맞출 때는 둘을 통일해야 합니다.

**라벨에 +1.5mm 편향** — 표면 재구성 커널이 표면을 살짝 부풀립니다. 전체에 일관되게
적용되므로 학습에는 무해하지만 실측과 맞출 때 감안해야 합니다.

**height_field_tool.py의 샘플 반경은 27mm 고정** — CONFIG에서 CUP_INNER_R을 27mm 아래로
줄이면 컵 밖을 샘플링하게 되므로, 그 경우 SAMPLE_R도 같이 줄여야 합니다.

**실제 수위가 설정값과 다를 수 있음** — 입자 샘플링과 표면 재구성 부풀림 때문에
WATER_LEVEL 설정값보다 정착 후 실제 수면이 몇 mm 높게 나옵니다.
실측: 85mm 설정 -> 92.5mm, 92mm 설정 -> 97.3mm (대략 +5~7mm).
정확한 수위가 필요하면 정착 프레임(SETTLE_T)의 메시에서 실제 수면을 재고
WATER_LEVEL을 그만큼 낮춰 다시 돌리세요.

**코드 수정 시 함정 2가지**
1. flags.initDomain(phiWalls=phiObs) 는 넘겨받은 phiObs를 초기화합니다. 컵 levelset을 먼저
   만들고 호출하면 컵이 사라지므로, 반드시 initDomain 이후에 컵을 join해야 합니다.
2. IDP의 push-out은 정지 장애물 전제라 이동 컵에서 물이 샙니다. clampToCupAxis가 그 보완입니다.
   (컵 벽 두께 안에 들어온 입자만 안쪽으로 되돌리고, 테두리 위로 넘치는 물은 건드리지 않음)

**성능** — 표면 재구성이 가장 무거워서, 궤적 프레임에 해당하는 시각에만 메시를 만듭니다
(시뮬 1200여 프레임 중 225개만 저장, 약 5배 절감).

## 환경
Blender 4.5.3 LTS / mantaflow 0.13 / Ubuntu 22.04 / RTX 3070