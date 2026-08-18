# 새 세라프 계정 준비 절차

계정 정보(아이디/비밀번호)를 받은 뒤 이 문서를 위에서부터 따라가면 된다.
`ACC` 만 바꿔 쓰면 나머지는 그대로 복사해 붙일 수 있다.

    export ACC=<새계정>            # 예: export ACC=shpark
    export SER="ssh -p 30080 $ACC@moana.khu.ac.kr"

지금 계정(shawnbest)에서 확인된 값은 비교용으로 함께 적었다.

---

## 0. 받자마자 확인할 것 (5분)

한 번에 확인하는 명령이다. 출력 전체를 보고 아래 표와 비교한다.

    $SER 'echo "== 계정"; whoami; id -gn
    echo "== HOME / DATA"; echo HOME=$HOME; ls -ld /data/$USER 2>&1 | head -1
    echo "== 용량"; df -h /data | tail -1; du -sh /data/$USER 2>/dev/null
    echo "== SLURM account"; sacctmgr -n show assoc where user=$USER format=Account,Partition,QOS%30
    echo "== QOS 한도"; sacctmgr -n show qos format=Name,MaxSubmitJobsPU,MaxJobsPU,MaxTRESPU%40
    echo "== 파티션"; sinfo -o "%20P %10a %10l %6D %10T %20G" | head
    echo "== 노드별 GPU"; sinfo -N -o "%20N %10T %20G" | head -20
    echo "== 이미 있는 것"; ls -d /data/$USER/{mantaflow,blender-4.5.3-linux-x64,anaconda3,miniconda3} 2>&1'

확인 포인트

| 항목 | shawnbest 기준 | 새 계정에서 볼 것 |
|---|---|---|
| `$HOME` | `/home/shawnbest` (계산 노드에 공유 안 됨) | `/data/$USER` 와 다르면 아래 "경로 함정" 참고 |
| SLURM account | `ugrad_ce` | 파티션 접근 권한이 이 account 로 걸린다 |
| 파티션 | `batch_ce_ugrad` | 이름이 다르면 `slurm/*.sh` 의 `-p` 를 바꿔야 한다 |
| QOS `MaxSubmitJobsPU` | 10 | 한 번에 큐에 넣을 수 있는 잡 수. 넘으면 `sbatch` 가 거부된다 |
| QOS `MaxJobsPU` | 2 | 동시에 RUNNING 가능한 잡 수 |
| QOS `MaxTRESPU gres/gpu` | **1** | 실질 병렬도. 노드 4개를 쓰려면 여기가 4 이상이어야 한다 |
| `/data` 여유 | 98T | 궤적당 약 190MB(결과) + 시뮬 중간 메시 약 190MB |

> **노드 4개를 쓰려면 `MaxTRESPU gres/gpu` 와 `MaxJobsPU` 가 둘 다 4 이상이어야 한다.**
> 담당자에게 요청할 때 이 두 값을 명시하는 편이 확실하다. 값이 1이면 노드가 많아도
> 순차 실행이라 지금과 속도가 같다.

---

## 1. 폴더와 파일 배치

    $SER 'mkdir -p /data/$USER/water_cup/{batch,logs,settle_cache}'

저장소에서 올린다(로컬에서 실행).

    cd <저장소>
    scp -P 30080 scripts/{height_field_tool,extract_gen,render_gen,make_traj,check_labels,debug_frame,make_sheet,make_sample,overlay_label,check_renders}.py $ACC@moana.khu.ac.kr:/data/$ACC/water_cup/
    scp -P 30080 slurm/batch_job.sh                 $ACC@moana.khu.ac.kr:/data/$ACC/water_cup/
    scp -P 30080 water_scene_final.blend            $ACC@moana.khu.ac.kr:/data/$ACC/water_cup/
    scp -P 30080 traj/batch/traj_00*.txt traj/batch/params.csv $ACC@moana.khu.ac.kr:/data/$ACC/water_cup/batch/
    ssh -p 30080 $ACC@moana.khu.ac.kr 'mkdir -p /data/'$ACC'/mantaflow/scenes'
    scp -P 30080 scenes/cup_idp_gen.py              $ACC@moana.khu.ac.kr:/data/$ACC/mantaflow/scenes/

## 2. Blender 4.5.3

    $SER 'cd /data/$USER && wget -q https://download.blender.org/release/Blender4.5/blender-4.5.3-linux-x64.tar.xz &&
          tar xf blender-4.5.3-linux-x64.tar.xz && rm blender-4.5.3-linux-x64.tar.xz &&
          ./blender-4.5.3-linux-x64/blender --version'

렌더는 GPU(OPTIX/CUDA)를 쓰므로 계산 노드에서 한 번 확인한다(4단계 시험 실행에서 로그의
`[gpu]` 줄로 확인된다).

## 3. conda 환경 (python 3.10 + numpy)

mantaflow 빌드와 실행에 쓴다.

    $SER 'cd /data/$USER && wget -q https://repo.anaconda.com/archive/Anaconda3-2024.10-1-Linux-x86_64.sh &&
          bash Anaconda3-2024.10-1-Linux-x86_64.sh -b -p /data/$USER/anaconda3 && rm Anaconda3-*.sh &&
          source /data/$USER/anaconda3/etc/profile.d/conda.sh &&
          conda create -y -n fluid python=3.10 numpy && conda activate fluid && python -c "import numpy;print(numpy.__version__)"'

> `batch_job.sh` 가 `source /data/$USER/anaconda3/...` 를 부른다. miniconda 로 깔면
> 그 줄의 경로를 바꿔야 한다.

## 4. mantaflow 빌드 (우리가 수정한 소스 포함)

`src/implicitdensityprojection.cpp` 는 우리가 고친 파일이라 반드시 덮어써야 한다.

    scp -P 30080 src/implicitdensityprojection.cpp $ACC@moana.khu.ac.kr:/tmp/
    $SER 'source /data/$USER/anaconda3/etc/profile.d/conda.sh && conda activate fluid
          cd /data/$USER && git clone https://bitbucket.org/mantaflow/manta.git mantaflow_src 2>/dev/null
          cp /tmp/implicitdensityprojection.cpp /data/$USER/mantaflow_src/source/plugin/ 2>/dev/null || \
          cp /tmp/implicitdensityprojection.cpp /data/$USER/mantaflow_src/source/
          mkdir -p /data/$USER/mantaflow/build && cd /data/$USER/mantaflow/build
          cmake /data/$USER/mantaflow_src -DGUI=OFF -DOPENMP=ON && make -j8 && ./manta --help | head -3'

> 지금 계정의 빌드는 `/data/$USER/mantaflow/build/manta` 에 있고 씬은
> `/data/$USER/mantaflow/scenes/` 에서 읽는다. 배치 잡이 이 경로를 쓴다.
> 빌드 소스 위치가 다르면 `batch_job.sh` 의 `SCENE=` 과 `cd` 경로를 맞춘다.

## 5. 정착 캐시 미리 만들기 (병렬 실행 전 필수)

수위 4종의 캐시를 **순차로** 먼저 만든다. 이유는 아래 "병렬 실행 위험" 참고.

    $SER 'cd /data/$USER/water_cup && sbatch --array=1,6,12,18%1 batch_job.sh'

`params.csv` 기준 1=55mm, 6=65mm, 12=75mm, 18=85mm 라 이 넷이면 4종이 다 만들어진다.
`%1` 이 순차 실행을 강제한다. 끝나면 확인한다.

    $SER 'ls -la /data/$USER/water_cup/settle_cache/'

`w55_g152_v2.uni/.json`, `w65_...`, `w75_...`, `w85_...` 8개 파일(+ _vel 4개)이 보이면 된다.

## 6. 시험 실행 (1~2개)

    $SER 'cd /data/$USER/water_cup && sbatch --array=21,23 batch_job.sh'

끝나면 검증한다.

    $SER 'cd /data/$USER/water_cup
          source /data/$USER/anaconda3/etc/profile.d/conda.sh; conda activate fluid
          for i in 0021 0023; do
            echo "== $i"; for c in e n w s; do echo -n "$c 라벨 $(ls out/$i/height_$c/*.npy|wc -l) 이미지 $(ls out/$i/${c}_*.png|wc -l)  "; done; echo
            python3 check_labels.py out/$i | grep -E "^\[1\]|^\[2\]|총평"
            grep -c "^\[warn\]" logs/sim_*_${i#000}.log
          done'

통과 기준
- 라벨 4방향 × 프레임 수, 이미지 4방향 × 프레임 수가 같다
- `유효 셀 수 616 : OK`, `NaN 마스크 일치 : OK`, `총평: 모두 통과`
- `[warn] ... 화면 밖` 0건

## 7. 나머지 전량

QOS 제출 한도(shawnbest 기준 10) 안에서 나눠 던진다.

    $SER 'cd /data/$USER/water_cup && sbatch --array=2-11 batch_job.sh'
    # 큐가 비면 다음 묶음
    $SER 'cd /data/$USER/water_cup && sbatch --array=12-20,22,24,25 batch_job.sh'

진행 확인(한 줄):

    $SER 'cd /data/$USER/water_cup && for i in $(seq -w 1 25); do n=$(ls out/00$i/*.png 2>/dev/null|wc -l);
      m=$(ls out/00$i/height_*/*.npy 2>/dev/null|wc -l); [ "$n" -gt 0 ] && [ "$n" -eq "$m" ] && D="$D $i"; done
      echo "완료:$D | 실행중: $(squeue -u $USER -h -t R -o "%K")"'

완료된 것부터 로컬로 내린다.

    REMOTE=$ACC@moana.khu.ac.kr RROOT=/data/$ACC/water_cup scripts/fetch_traj.sh $(seq 1 25)

---

## 경로 함정 (예전에 실제로 겪은 것)

- **`$HOME` 은 `/data/$USER` 가 아니다.** 세라프에서 `$HOME=/home/<계정>` 이고 이 경로는
  계산 노드마다 다르다(공유되는 노드도 있고 아닌 노드도 있다). 로그인 노드에서 심볼릭
  링크를 걸어도 계산 노드에서는 안 보인다.
  → `extract_gen.py` 는 측정기를 **자기 파일 위치 기준**으로 찾는다(`__file__`).
    `HFT_PATH` 로 덮어쓸 수 있다. 스크립트를 옮길 때 `height_field_tool.py` 를 같은
    폴더에 두기만 하면 된다.
  → timing 기록도 `$HOME` 이 아니라 메시 폴더 옆에 쓴다(`TIMING_LOG` 로 변경 가능).
- `batch_job.sh` / `traj_job.sh` 는 `/data/$USER` 를 쓴다. 계정만 바뀌면 수정이 필요 없다.
- 파티션 이름이 다르면 `slurm/*.sh` 의 `#SBATCH -p` 를 모두 바꾼다.

---

## 병렬 실행 위험과 대책

지금까지는 GPU 1개라 순차였다. 4개를 동시에 돌리면 아래가 새로 문제가 된다.

### 1) 정착 캐시 경쟁 — 가장 위험

`scenes/cup_idp_gen.py` 는 수위별로 `settle_cache/wNN_g152_v2.uni` 를 공유한다.
흐름은 "있으면 읽고, 없으면 계산해서 쓴다" 이다. 같은 수위의 잡 두 개가 동시에 시작하면

- 둘 다 "캐시 없음" 으로 판단해 각자 계산한 뒤 같은 파일에 쓴다.
  `.uni`(입자) 와 `.json`(컵 배치)이 **서로 다른 잡의 것으로 섞이면** 물이 컵 밖에서
  시작한다. 예전에 25개 중 11개가 라벨 0셀로 죽은 것이 이 원인이었다.
- 읽는 잡이 **쓰다 만 파일**을 읽을 수 있다.

**적용한 대책 (코드)**: 캐시를 임시 이름으로 쓴 뒤 `os.replace()` 로 넣는다(같은
파일시스템에서 원자적). 판정 기준인 `.json` 을 **마지막에** 넣어서, 읽는 쪽이
`.uni` 와 `.json` 을 둘 다 본 시점에는 내용이 완성돼 있다. 읽기 직전에 존재를 다시
확인해 사라졌으면 자기 정착으로 되돌린다.

**운영 대책 (권장)**: 그래도 **5단계처럼 수위 4종 캐시를 먼저 순차로 만들어 두고**
전량을 던진다. 그러면 이후 잡은 전부 읽기만 한다. 중복 계산(궤적당 3~4분)도 아낀다.

### 2) 같은 폴더에 동시 쓰기

| 경로 | 동시 충돌 | 판단 |
|---|---|---|
| `batch/scene_XXXX.py` | 인덱스별 이름 | 안전 |
| `sim_XXXX/`, `out/XXXX/` | 인덱스별 | 안전 |
| `settle_cache/` | 수위별 공유 | 위 대책으로 해결 |
| `timing_log.csv` | **모든 라벨 잡이 append** | 한 줄씩이라 실무상 문제는 적지만, NFS 에서 append 원자성이 보장되지 않는다. 신경 쓰이면 `TIMING_LOG=$W/logs/timing_$I.csv` 로 잡마다 나눈다 |

### 3) 로그 충돌

`#SBATCH -o .../sim_%A_%a.log` 는 잡ID+배열인덱스라 겹치지 않는다. 안전.

### 4) 그 밖에

- 같은 노드에 여러 잡이 붙으면 GPU 메모리를 나눠 쓴다. 렌더는 프레임당 0.5GB 수준이라
  여유롭지만, 시뮬(mantaflow)은 CPU/OpenMP 라 `--cpus-per-gpu=8` 이 노드 코어를 넘지
  않는지 본다.
- `/data` 는 NFS 다. 25개를 동시에 쓰면 I/O 가 몰린다. 결과는 궤적당 190MB 라 문제
  없지만, 시뮬 중간 메시(궤적당 약 190MB)까지 겹치면 순간적으로 커진다.

---

## 예전 오류에 대한 방어 (현재 코드에 반영됨)

| 예전 증상 | 방어 | 위치 |
|---|---|---|
| 유효 셀 0 프레임에서 `vv.max()` 예외로 시퀀스 전체가 죽음 | `MIN_VALID`(기본 62) 미만이면 그 프레임만 NaN 으로 저장하고 계속 | `extract_gen.py` |
| Blender 가 파이썬 예외로 죽어도 종료코드 0 → 라벨 없이 렌더만 40분 | 라벨 파일 수를 세서 0이면 잡 중단 | `batch_job.sh` |
| 측정기를 `~/water_cup` 에서 찾다 계산 노드에서 실패 | 스크립트 자기 위치 기준으로 찾음(`__file__`), `HFT_PATH` 로 덮어쓰기 | `extract_gen.py` |
| `hf_grid` 가 물을 가림 | 숨길 것을 나열하지 않고 **남길 것(water, Plane)만 지정** | `render_gen.py` |
| 물이 화면 밖으로 나감 | 프레임마다 투영해서 벗어나면 `[warn]` | `render_gen.py` |
| 정착 캐시 배치 불일치 | 캐시에 컵 배치를 함께 저장, 안 맞으면 자기 정착 | `cup_idp_gen.py` |

검증 도구

    python3 check_labels.py out/XXXX      # 라벨: 616셀·마스크·4방향 회전 관계
    python3 check_renders.py out/XXXX     # 렌더: 화면 밖·인공 절단·빈 프레임
    python3 debug_frame.py sim_XXXX 84    # 문제 프레임의 물 메시 위치

---

# 부록: ariel 계정 (sh.park0203) 실측 정보와 실행 절차

moana(shawnbest)와 다른 점이 많아 따로 정리한다. 아래 값은 2026-08-18 직접 확인한 것이다.

## 확인된 환경

| 항목 | moana | **ariel** |
|---|---|---|
| 접속 | `ssh -p 30080 shawnbest@moana.khu.ac.kr` | `ssh sh.park0203@ariel.khu.ac.kr` (키 인증) |
| 작업 경로 | `/data/$USER` | **`/nas2/data/$USER`** (220T 중 112T 여유) |
| `$HOME` | 계산 노드와 공유 안 됨 | **공유됨** |
| conda | `anaconda3` | **`miniconda3`** (`fluid` = python 3.10.20 + numpy 2.2.6) |
| SLURM account / QOS | `ugrad_ce` / `ugrad` | **`grad` / `grad`** |
| 파티션 | `batch_ce_ugrad` | **`batch_grad`** (배치) / `debug_grad` (대화형 전용) |
| 큐 제출 한도 | 10 | **20** |
| 동시 실행 | 2 | **10** |
| GPU 한도 | 1 | **4** |
| GPU | RTX A5000 | ariel-v* = **RTX A5000 24GB**, ariel-g* = **RTX 3090 24GB** |

이미 설치돼 있어 **새로 깔 것이 없다**: Blender 4.5.3 LTS, miniconda3(`fluid`),
mantaflow 빌드(`/nas2/data/$USER/mantaflow/build/manta`). mantaflow 소스
`implicitdensityprojection.cpp` 는 우리 수정본과 md5 가 같고 빌드가 그 이후라
**재빌드 불필요**.

## 제출 규칙 (실측)

이 클러스터에는 제출 검사 플러그인이 있다. 직접 시험해 확인한 결과다.

1. **대화형(`srun`)은 이름에 `debug` 가 든 파티션에만** 넣을 수 있다.
   배치는 `batch_grad` 로 보낸다.
2. **`--gres=gpu:1` 은 노드를 `-w` 로 하나 지정해야만 통과한다.**
   `-x ariel-k1,...`, `-x m1,...`, `-x ariel-k[1-2],...`, `--exclude=...` 는 **전부 거부**됐다.
   `-w ariel-v[1-13]` 처럼 범위를 주면 `-N 13-1` 오류가 난다(노드 목록이 곧 노드 수).
   → 통과하는 유일한 형태는 **`-w <노드 하나>`**.
3. 쓸 수 있는 노드: `ariel-g[1-5]`, `ariel-v[1-13]`.
   `ariel-k1,k2,m1,m2,n1` 은 high_perf 라 QOS(`gres/gpu:high_perf=0`)상 못 쓴다.

그래서 `slurm/submit_ariel.sh` 가 인덱스를 노드에 돌아가며 배정하고
**노드마다 배열을 하나씩(`%1`)** 던진다. 노드 4개 = 동시 4개 = GPU 한도와 일치.

## 실행 절차

### 0) 파일 올리기 (로컬에서)

    A=sh.park0203@ariel.khu.ac.kr
    R=/nas2/data/sh.park0203
    ssh $A "mkdir -p $R/water_cup/{batch,logs}"
    scp scripts/{height_field_tool,extract_gen,render_gen,make_traj,check_labels,debug_frame,make_sheet,make_sample,overlay_label,check_renders}.py $A:$R/water_cup/
    scp slurm/batch_job_ariel.sh slurm/submit_ariel.sh slurm/progress_ariel.sh $A:$R/water_cup/
    scp water_scene_final.blend $A:$R/water_cup/
    scp traj/batch/traj_00*.txt traj/batch/params.csv $A:$R/water_cup/batch/
    scp scenes/cup_idp_gen.py $A:$R/mantaflow/scenes/
    ssh $A "chmod +x $R/water_cup/*.sh"

> 클러스터에 있던 스크립트는 8월 12~13일 것이라 그동안의 수정이 하나도 없다.
> 반드시 덮어써야 한다. 궤적과 params.csv 도 새 것으로 바꾼다.

### 1) 정착 캐시 먼저 (수위 4종, 병렬로 안전)

수위가 다르면 캐시 파일도 다르므로 **서로 경쟁하지 않는다.** 1/6/12/18 은
각각 55/65/75/85mm 라 4개를 동시에 돌려도 안전하고, 이 4개는 결과물까지 완성된다.

    ssh $A "cd $R/water_cup && ./submit_ariel.sh 1 6 12 18"

끝나면 캐시 4종이 생겼는지 확인한다.

    ssh $A "ls $R/water_cup/settle_cache/*.json"

### 2) 시험 확인

    ssh $A "cd $R/water_cup && source $R/miniconda3/etc/profile.d/conda.sh && conda activate fluid
            for i in 0001 0018; do echo == \$i
              for c in e n w s; do echo -n \"\$c 라벨 \$(ls out/\$i/height_\$c/*.npy|wc -l) 이미지 \$(ls out/\$i/\${c}_*.png|wc -l)  \"; done; echo
              python3 check_labels.py out/\$i | grep -E '총평'
              python3 check_renders.py out/\$i | grep -E '총평'
            done"

통과 기준: 라벨·이미지 개수가 같고, 두 검사 모두 `모두 정상`/`모두 통과`.

### 3) 나머지 21개

큐 한도가 20이라 두 번에 나눈다.

    ssh $A "cd $R/water_cup && ./submit_ariel.sh 2 3 4 5 7 8 9 10 11 13 14 15 16"   # 13개
    # 큐가 비어가면
    ssh $A "cd $R/water_cup && ./submit_ariel.sh 17 19 20 21 22 23 24 25"           # 8개

`submit_ariel.sh` 는 큐 여유를 먼저 확인하고 한도를 넘으면 던지지 않고 알려준다.

### 4) 진행 확인과 회수

    ssh $A "$R/water_cup/progress_ariel.sh"
    REMOTE=$A RROOT=$R/water_cup PORT=22 scripts/fetch_traj.sh $(seq 1 25)

> `fetch_traj.sh` 는 `PORT` 를 환경변수로 받는다(ariel 은 22).

## 예상 소요 시간

궤적당 약 40~47분(시뮬 5~13분 + 라벨 4방향 1분 + 렌더 400장 31분).
캐시가 있으면 시뮬이 4분쯤 빨라진다.

- 1단계(캐시 4개, 병렬 4): **약 50분**
- 나머지 21개, 동시 4개: 21/4 = 6묶음 × 약 42분 = **약 4시간 20분**
- **합계 약 5시간** (moana 에서 순차로 돌리면 18시간)

ariel-g* 는 RTX 3090, ariel-v* 는 A5000 이다. Cycles 렌더는 3090 이 대체로
20~30% 빠르므로 g 노드에 배정된 궤적이 먼저 끝난다. 시간 예측은 느린 쪽(A5000)
기준이다.
