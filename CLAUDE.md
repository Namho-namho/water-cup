# water-cup — 로봇 컵 운반 유체 데이터셋 파이프라인

## 목적
로봇팔이 물컵을 옮기는 장면에서 (렌더 이미지, 수면 높이 필드) 쌍을 생성한다.
CVPR 2027 제출 목표. 이미지로부터 액면을 복원하는 비전 모델의 학습 데이터가 된다.

## 파이프라인
Genesis(궤적) → mantaflow IDP-APIC(유체 시뮬) → Blender 4.5.3(렌더 + 라벨)

시뮬이 meta.json에 설정을 기록하고 렌더·라벨이 그것을 읽는다.
궤적을 바꿔도 렌더·라벨 스크립트는 수정할 필요가 없다.

## 파일 구조
- `scenes/cup_idp_gen.py` — mantaflow 씬. 상단 CONFIG만 바꿔 쓴다
- `scripts/height_field_tool.py` — 높이 필드 추출 도구 (extract_gen이 exec로 읽음)
- `scripts/extract_gen.py` — 라벨 생성 진입점 (CAM_NAME / OUT_LABELS / F_START / F_END)
- `scripts/check_labels.py` — 4방향 라벨 검증 (유효셀·평균·회전 관계)
- `scripts/render_gen.py` — Blender 렌더
- `scripts/gen_traj_batch.py` — 궤적 일괄 생성기
- `scripts/make_traj.py` — Genesis npy → 궤적 txt 변환
- `src/implicitdensityprojection.cpp` — 수정한 mantaflow 소스
- `slurm/` — 세라프 배치 잡
- `traj/batch/` — 궤적 25개 + params.csv
- `water_scene_final.blend` — 컵·물·카메라·조명

## 규격
- 격자 152×152×208, 셀 크기 2.42mm (H = 0.368/152)
- 컵: 안지름 56mm, 바깥지름 70mm, 높이 100mm, 바닥 두께 6mm
- 수위 55 / 65 / 75 / 85mm (params.csv에 기록)
- 궤적 프레임 간격 8ms, 시뮬 프레임당 TFRAME=5.09, 정착 SETTLE_T=200
- 표면 재구성: improvedParticleLevelset, radiusFactor 2.2, smoothen 3
- 높이 필드: 32×32 float, 단위 m, 컵 안바닥 기준, 샘플 반경 27mm, 유효 616셀, 나머지 NaN
- 라벨 격자: 평면은 컵 축에 수직(컵 로컬 xy), 광선은 컵 축 반대 방향, 높이는 컵 축 방향
  거리. 이 평면 안에서 격자를 몇 도 돌릴지만 카메라가 정한다. j축 = 카메라 광축의 방위
  성분을 컵 평면에 투영한 벡터, i축 = j축과 수직(i×j = 컵 축). 광축을 부감각까지 통째로
  투영하면 컵이 기울 때 네 방향이 90도씩 벌어지지 않는다. 컵 자기축 회전은 라벨에 안 들어감
- 환경변수: `LABEL_FRAME=camera`(기본) / `cup`(예전 방식),
  `GRID_PLANE=cup`(기본) / `world`(월드 수평면+수직 광선. 컵이 기울면 자유수면 대신
  물-벽 접촉선을 재는 셀이 생겨 권장하지 않음), `CAM_AZIM=view`(기본, 광축) / `position`
- 카메라: Camera_e / _n / _w / _s (45도 부감, 컵에서 1.35m). CAM_NAME으로 지정
- 마커: cup_marker_x (컵 로컬 +x에 붙은 띠). 렌더 스크립트가 매 프레임 위치를 갱신하되
  `SHOW_MARKER=1` 일 때만 렌더에 나온다 (기본 0 = 숨김)

## 환경
- 로컬: airlab-desktop, Ubuntu 22.04, RTX 3070
- 클러스터: 세라프 SLURM (moana.khu.ac.kr:30080, /data/<계정>/)
- mantaflow 빌드: `cmake .. -DGUI=OFF -DOPENMP=ON`
- Blender는 alias 말고 전체 경로 사용

## 알려진 함정
1. `flags.initDomain(phiWalls=phiObs)`는 넘겨받은 phiObs를 초기화한다. 컵 levelset을
   먼저 만들고 호출하면 컵이 사라지므로 initDomain 이후에 컵을 join해야 한다.
2. IDP의 push-out은 정지 장애물 전제라 이동 컵에서 물이 샌다. `clampToCupAxis`가 보완.
3. 표면 재구성이 입자보다 바깥에 표면을 만든다. 물이 격하게 튄 뒤에는 성긴 입자층까지
   감싸서 수면이 실제보다 2~5mm 높게 기록된다. 잔잔할 때는 0.3mm 수준.
4. DT_REAL과 궤적 생성 설정이 어긋나면 에러 없이 시뮬 속도만 달라진다.
5. Blender 렌더에서 좌표를 색으로 저장할 때는 view_transform을 'Standard'로 해야 한다.

## 작업 규칙
- 파일을 수정하면 `python3 -c "compile(open(...).read(),'x','exec')"` 로 문법을 확인한다
- 기존 동작을 바꾸는 수정은 환경변수로 켜고 끌 수 있게 한다
- 경로는 `~/water_cup` 기준. 세라프용은 실행 시 sed로 치환
- 한국어로 소통한다