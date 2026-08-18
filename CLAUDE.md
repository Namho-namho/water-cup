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
- `scripts/debug_frame.py` — 문제 프레임의 물 메시 위치 진단 (Blender 없이)
- `scripts/overlay_label.py` — 렌더 이미지 위에 라벨 격자 겹쳐 보기
- `scripts/make_sheet.py` — 4방향 이미지+높이필드 비교판
- `scripts/make_sample.py` — 팀 공유용 샘플 (이미지+라벨 짝, 규격 포함)
- `scripts/check_renders.py` — 렌더 전수 검사 (화면 밖·인공 절단)
- `scripts/fetch_traj.sh` — 세라프 결과를 로컬 dataset/ 로 받아 검증
- `scripts/render_gen.py` — Blender 렌더
- `scripts/gen_traj_batch.py` — 궤적 일괄 생성기
- `scripts/make_traj.py` — Genesis npy → 궤적 txt 변환
- `src/implicitdensityprojection.cpp` — 수정한 mantaflow 소스
- `slurm/` — 세라프 배치 잡
- `docs/SERAPH_SETUP.md` — 새 계정 준비 절차, 병렬 실행 위험, 첫 확인 명령
- `traj/batch/` — 궤적 25개 + params.csv
- `water_scene_final.blend` — 컵·물·카메라·조명

## 규격
- 격자 152×152×208, 셀 크기 2.42mm (H = 0.368/152)
- 컵: 안지름 56mm, 바깥지름 70mm, 높이 100mm, 바닥 두께 6mm
- 수위 55 / 65 / 75 / 85mm (params.csv에 기록)
- 궤적 프레임 간격 8ms, 시뮬 프레임당 TFRAME=5.09, 정착 SETTLE_T=200
- 표면 재구성: improvedParticleLevelset, radiusFactor 2.2, smoothen 3
- 높이 필드: 32×32 float, 단위 m, 컵 안바닥 기준, 샘플 반경 27mm, 유효 616셀, 나머지 NaN
  (`height_{e,n,w,s}/height_XXXX.npy`). 격자 = 컵 축에 수직인 평면, 광선 = 컵 축 방향,
  높이 = 컵 안바닥에서 컵 축 방향 거리
- 높이 상한 없음. 테두리(94mm) 위로 솟거나 넘치는 물도 값으로 담는다. 공중의 물보라는
  높이가 아니라 두께로 거른다: 교점을 (윗면, 아랫면) 쌍으로 보고 `MIN_THICK_MM`(기본 5)
  보다 얇으면 건너뛴다. 안전 상한은 `MAX_H_MM`(기본 300 = 컵 높이 3배)
- NaN의 의미: 물이 없거나(광선이 아무것도 못 맞음, 컵 바닥 노출) 얇은 물보라뿐인 자리.
  "물이 높아서 잘린" NaN은 더 이상 없다
- 격자 회전각(두 버전 공통): j축 = 카메라 광축의 방위 성분을 격자 평면에 투영한 벡터, i축 = j축과 수직(i×j = 컵 축). 광축을 부감각까지 통째로
  투영하면 컵이 기울 때 네 방향이 90도씩 벌어지지 않는다. 컵 자기축 회전은 라벨에 안 들어감
- 환경변수: `LABEL_FRAME=camera`(기본) / `cup`(예전 방식),
  `GRID_PLANE=cup`(A) / `world`(B), `CAM_AZIM=view`(기본, 광축) / `position`
- 카메라: Camera_e / _n / _w / _s. 네 대는 완전 대칭이어야 한다 — 같은 수평거리
  1.202m, 같은 높이 1.352m, 같은 렌즈 57.09mm, 같은 부감각 45도, shift 0,
  방위각만 90도씩(180/270/0/90). 목표점 cam_target (0.55, 0.19, 0.15).
  거리는 25개 궤적의 물이 네 방향 모두에서 화면 안에 들어오는 최소값이다
  (0.955m에서는 shake 85mm 궤적이 위쪽에서 잘렸다). CAM_NAME으로 지정
- 마커: cup_marker_x (컵 로컬 +x에 붙은 띠). 렌더 스크립트가 매 프레임 위치를 갱신하되
  `SHOW_MARKER=1` 일 때만 렌더에 나온다 (기본 0 = 숨김)
- 학습용 렌더: `WATER_ONLY=1` — 컵·마커 숨김, 월드/바닥 흰색, view_transform=Standard.
  컵 밖 물 제거는 `WATER_CLIP=cylinder`(기본, 안반경 원통과 불리언 교집합) /
  `component`(컵에 걸친 연결 덩어리만) / `radius`(삼각형 자르기, 절단면이 드러나므로
  쓰지 말 것) / `off`. 테두리 위 물은 남긴다(`WATER_CLIP_RIM=1` 이면 컵 높이에서 자름)
- 렌더 중 물이 화면 밖으로 나가면 `[warn] fXXXX 물의 N%가 화면 밖` 을 찍는다.
  로그에서 이 줄이 나오면 카메라를 네 대 함께 뒤로 물려야 한다
- 정착 캐시: `settle_cache/wNN_g152_v2.uni` + 같은 이름 `.json`(컵 배치 기록).
  쓸 때는 임시 이름으로 쓴 뒤 `os.replace`로 넣고 `.json`을 마지막에 넣는다.
  여러 잡이 동시에 같은 수위를 만들어도 반쯤 쓰인 캐시를 읽지 않는다.
  병렬 실행 전에는 수위 4종 캐시를 순차로 먼저 만들어 두는 것이 안전하다.
  캐시를 쓰면 캐시의 컵 배치를 채택하고, 그 배치로 궤적이 도메인을 벗어나면
  캐시를 버리고 자기 정착을 계산한다. v1 캐시(위치 정보 없음)는 쓰지 않는다

## 환경
- 로컬: airlab-desktop, Ubuntu 22.04, RTX 3070
- 클러스터: 세라프 SLURM (moana.khu.ac.kr:30080, /data/<계정>/)
- mantaflow 빌드: `cmake .. -DGUI=OFF -DOPENMP=ON`
- Blender는 alias 말고 전체 경로 사용

## 알려진 함정
1. `flags.initDomain(phiWalls=phiObs)`는 넘겨받은 phiObs를 초기화한다. 컵 levelset을
   먼저 만들고 호출하면 컵이 사라지므로 initDomain 이후에 컵을 join해야 한다.
2. IDP의 push-out은 정지 장애물 전제라 이동 컵에서 물이 샌다. `clampToCupAxis`가 보완.
2-1. 정착 캐시는 입자를 격자 절대 좌표로 저장하는데 컵 배치(cupCenterX/cupBottom/
   cupCenterZ)는 궤적의 이동 범위에서 계산돼 궤적마다 다르다. 배치를 맞추지 않고
   캐시를 읽으면 물이 컵 밖에서 시작해 라벨 유효 셀이 0이 된다. v2 캐시는 배치를
   같이 저장해 이 문제를 막는다.
3. 표면 재구성이 입자보다 바깥에 표면을 만든다. 물이 격하게 튄 뒤에는 성긴 입자층까지
   감싸서 수면이 실제보다 2~5mm 높게 기록된다. 잔잔할 때는 0.3mm 수준.
   같은 이유로 입자 하나짜리 물방울도 지름 10mm 안팎으로 부풀어, 두께 판정(5mm)으로는
   안 걸러진다. 대신 렌더에도 같은 물방울이 보이므로 이미지-라벨은 어긋나지 않는다.
4. DT_REAL과 궤적 생성 설정이 어긋나면 에러 없이 시뮬 속도만 달라진다.
5. Blender 렌더에서 좌표를 색으로 저장할 때는 view_transform을 'Standard'로 해야 한다.

## 작업 규칙
- 파일을 수정하면 `python3 -c "compile(open(...).read(),'x','exec')"` 로 문법을 확인한다
- 기존 동작을 바꾸는 수정은 환경변수로 켜고 끌 수 있게 한다
- 경로는 `~/water_cup` 기준. 세라프용은 실행 시 sed로 치환
- 한국어로 소통한다