#!/usr/bin/env python3
"""궤적 일괄 생성기.

인덱스를 받아 유형과 파라미터를 무작위로 정하고, traj_curveG.py를 템플릿 삼아
이동 구간만 교체한 스크립트를 만들어 실행합니다.

사용:
    python gen_traj_batch.py <인덱스> [출력루트]
    python gen_traj_batch.py --params-only 1000    # params.csv만 미리 생성
"""
import os, sys, math, random, subprocess, csv

ROOT = os.path.expanduser(os.environ.get('TRAJ_ROOT', '~/water_cup/batch'))
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'traj_curveG.py')
WATER_LEVELS = [0.055, 0.065, 0.075, 0.085]
KINDS = ['static', 'curve', 'stop', 'shake', 'zigzag', 'tilt']

MARK = '    frame["save_on"] = True'
END  = '    settle(20)'   # 이동 구간 끝. 이후(내려놓기)는 저장 안 함


def params(idx):
    """인덱스로 결정되는 파라미터 (재현 가능)."""
    r = random.Random(20260812 + idx)
    k = KINDS[idx % len(KINDS)]
    p = {
        'idx': idx,
        'kind': k,
        'water': WATER_LEVELS[(idx // len(KINDS)) % len(WATER_LEVELS)],
        'dist': round(r.uniform(0.24, 0.40), 4),      # 이동 거리(m)
        'step': r.randint(5, 8),                       # 조각당 스텝(속도)
        'seg':  0,                                     # 아래에서 결정
    }
    _target = 300 if idx <= 11 else 400   # 1~11: 150프레임, 12~25: 200프레임
    p['seg'] = max(12, int(round(_target / float(p['step']))))
    if k == 'curve':
        p['amp'] = round(r.uniform(0.05, 0.18), 4)     # 곡선 세기
        p['amp0'] = round(r.uniform(0.02, 0.08), 4)
    elif k == 'stop':
        p['accel'] = r.choice([2, 3])                  # u^2 / u^3
    elif k == 'shake':
        p['sh_amp'] = round(r.uniform(0.015, 0.055), 4)  # 진폭(m)
        p['sh_cyc'] = round(r.uniform(1.0, 4.5), 2)      # 주기 수
        p['sh_axis'] = r.choice(['y', 'x'])              # y=좌우, x=앞뒤
    elif k == 'static':
        p['nudge'] = round(r.uniform(0.0, 0.02), 4)      # 아주 작은 흔들림(m)
    elif k == 'zigzag':
        p['zz_amp'] = round(r.uniform(0.04, 0.12), 4)
        p['zz_cyc'] = round(r.uniform(1.0, 3.0), 2)
    elif k == 'tilt':
        p['tilt_deg'] = round(r.uniform(6.0, 14.0), 2)   # 최종 기울기(도)
        p['tilt_cyc'] = round(r.choice([0.0, 1.0, 2.0]), 1)  # 0=단조증가, >0=흔들림
    elif k == 'vert':
        p['vz_amp'] = round(r.uniform(0.03, 0.10), 4)    # 상하 진폭(m)
        p['vz_cyc'] = round(r.uniform(1.0, 3.0), 2)      # 상하 주기 수
        p['tilt_deg'] = round(r.uniform(0.0, 8.0), 2)    # 기울기 동반
    return p


def body(p):
    """이동 구간 코드 생성."""
    k = p['kind']
    p['seg'] = max(12, int(round(200.0 / p['step'])))   # 총 ~200스텝 = 100프레임
    if k == 'curve':
        return f"""    import math as _m
    _N = {p['seg']}
    for _k in range(1, _N + 1):
        _u = _k / float(_N)
        _q = _u * _u
        _y = {p['dist']} * _q
        _amp = {p['amp0']} + {p['amp']} * _q
        _x = GRASP_X + _amp * _m.sin(_m.pi * _q)
        move_lin((_x, _y, Z_LIFT), side, {p['step']}, FINGER_GRASP)"""
    if k == 'stop':
        e = p['accel']
        return f"""    import math as _m
    _N = {p['seg']}
    for _k in range(1, _N + 1):
        _u = _k / float(_N)
        _q = _u ** {e}
        move_lin((GRASP_X, {p['dist']} * _q, Z_LIFT), side, {p['step']}, FINGER_GRASP)"""
    if k == 'shake':
        return f"""    import math as _m
    _N = {p['seg']}
    for _k in range(1, _N + 1):
        _u = _k / float(_N)
        _d = {p['sh_amp']} * _m.sin(2.0 * _m.pi * {p['sh_cyc']} * _u)
        _px = GRASP_X + (_d if '{p['sh_axis']}' == 'x' else 0.0)
        _py = _d if '{p['sh_axis']}' == 'y' else 0.0
        move_lin((_px, _py, Z_LIFT), side, {p['step']}, FINGER_GRASP)"""
    if k == 'static':
        return f"""    import math as _m
    _N = {p['seg']}
    for _k in range(1, _N + 1):
        _u = _k / float(_N)
        _y = {p['nudge']} * _m.sin(2.0 * _m.pi * 1.0 * _u)
        move_lin((GRASP_X, _y, Z_LIFT), side, {p['step']}, FINGER_GRASP)"""
    if k == 'tilt':
        cyc = p['tilt_cyc']
        expr = (f"{p['tilt_deg']} * _m.sin(2.0 * _m.pi * {cyc} * _u)" if cyc > 0
                else f"{p['tilt_deg']} * (_u * _u * (3.0 - 2.0 * _u))")
        return f"""    import math as _m
    _N = {p['seg']}
    for _k in range(1, _N + 1):
        _u = _k / float(_N)
        _q = _u * _u
        _tl = {expr}
        move_lin((GRASP_X, {p['dist']} * _q, Z_LIFT), side_quat(_tl), {p['step']}, FINGER_GRASP)"""
    if k == 'vert':
        return f"""    import math as _m
    _N = {p['seg']}
    for _k in range(1, _N + 1):
        _u = _k / float(_N)
        _q = _u * _u
        _sm = _u * _u * (3.0 - 2.0 * _u)
        _z = Z_LIFT + {p['vz_amp']} * _m.sin(2.0 * _m.pi * {p['vz_cyc']} * _u)
        _tl = {p['tilt_deg']} * _sm
        move_lin((GRASP_X, {p['dist']} * _q, _z), side_quat(_tl), {p['step']}, FINGER_GRASP)"""
    # zigzag
    return f"""    import math as _m
    _N = {p['seg']}
    for _k in range(1, _N + 1):
        _u = _k / float(_N)
        _y = {p['dist']} * (_u * _u)
        _x = GRASP_X + {p['zz_amp']} * _m.sin(2.0 * _m.pi * {p['zz_cyc']} * _u)
        move_lin((_x, _y, Z_LIFT), side, {p['step']}, FINGER_GRASP)"""


def make(idx, root=ROOT):
    p = params(idx)
    src = open(TEMPLATE).read()
    i = src.index(MARK) + len(MARK)
    j = src.index(END, i)
    out_name = f'traj_{idx:04d}'
    s = src[:i] + '\n' + body(p) + '\n    frame["save_on"] = False\n' + src[j:]
    s = s.replace('traj_curveG_only', f'{out_name}_only')
    compile(s, 'x', 'exec')
    os.makedirs(root, exist_ok=True)
    py = os.path.join(root, f'{out_name}.py')
    open(py, 'w').write(s)
    return p, py, out_name


if __name__ == '__main__':
    if sys.argv[1] == '--params-only':
        n = int(sys.argv[2])
        os.makedirs(ROOT, exist_ok=True)
        with open(os.path.join(ROOT, 'params.csv'), 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=[
                'idx','kind','water','dist','step','seg',
                'amp','amp0','accel','sh_amp','sh_cyc','zz_amp','zz_cyc',
                'tilt_deg','tilt_cyc','sh_axis','nudge'])
            w.writeheader()
            for i in range(1, n + 1):
                w.writerow(params(i))
        print(f'params.csv 생성: {n}개')
        sys.exit(0)

    idx = int(sys.argv[1])
    root = sys.argv[2] if len(sys.argv) > 2 else ROOT
    p, py, name = make(idx, root)
    print(f'[{idx}] {p["kind"]} water={p["water"]} dist={p["dist"]} -> {py}', flush=True)
    subprocess.run([sys.executable, py], check=True, cwd=os.path.dirname(py))
    # npy -> txt
    conv = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'make_traj.py')
    subprocess.run([sys.executable, conv,
                    os.path.expanduser(f'~/water_cup/{name}_only'),
                    os.path.join(root, f'{name}.txt')], check=True)
    print(f'[{idx}] 완료', flush=True)
