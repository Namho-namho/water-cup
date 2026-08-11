"""
Franka Panda grasps a water-filled cup *from the side* (horizontal gripper) and
then *shakes it vigorously* so the water sloshes over the rim and spills.

Same setup as main.py (SPH water, thin-walled non-convex cup, rigid weld grasp),
but the gripper approaches horizontally (pointing +X) and grips the cup body on
its +/-Y faces instead of from the top (see main_pour.py for the same side grasp).
Step 6 ("transport") is a violent shake: the welded hand drives a fast lateral
(+ optional vertical/tilt) oscillation about the lifted pose, so water is
repeatedly thrown over the rim. Tune the SHAKE_* block to range between "messy
slosh" and "empties the cup".

Run:
    python main_shake.py
Output:
    - live Genesis viewer (set SHOW_VIEWER=False to run headless)
    - an MP4 written to RECORD_PATH
"""

import os
import tempfile

import numpy as np
import trimesh
from scipy.spatial.transform import Rotation as R

import genesis as gs

# ----------------------------------------------------------------------------
# CONFIG  (the "intent" dial)
# ----------------------------------------------------------------------------
FILL_FRACTION = 0.75      # how full the cup is (fraction of inner height)
PARTICLE_SIZE = 0.0015   # SPH particle diameter (m); smaller = finer water, slower

# Shake parameters (the "vigor" dial). The shake is a per-step sinusoid whose
# acceleration is what flings the water out: shorter SHAKE_PERIOD (faster
# oscillation) and larger amplitudes/tilt all increase spillage.
SHAKE_CYCLES = 7         # number of back-and-forth shake cycles
SHAKE_AMP_Y  = 0.15      # lateral (side-to-side) shake amplitude (m)
SHAKE_AMP_Z  = 0.00      # vertical bob amplitude (m)
SHAKE_TILT   = 0.0      # peak wrist tilt during shake (deg) -> tips water over the rim
SHAKE_PERIOD = 40        # sim steps per shake cycle (smaller = faster = more violent)

# How the water is drawn. "recon" reconstructs a smooth liquid surface mesh from
# the particles each frame (via splashsurf) -> looks like real water instead of
# blobs. "particle" draws each SPH particle as a sphere (faster, debug-ish).
WATER_VIS_MODE = "recon"

# Renderer for the recorded camera frames:
#   "raytracer"  -> LuisaRender path tracer. Photorealistic: real refraction
#                   through the water surface + glass cup, reflections, HDRI
#                   lighting. Requires LuisaRender to be built (LuisaRenderPy
#                   importable after genesis). This is the only Genesis backend
#                   that makes water actually look like water. Slow per frame (see SPP).
#   "rasterizer" -> fast OpenGL preview. No refraction, so water reads as a
#                   translucent/plastic blob. Use for quick iteration.
# (The interactive viewer is always rasterized regardless of this setting.)
RENDERER = "rasterizer"
SPP      = 256           # ray-tracer samples/pixel (higher = cleaner, slower). 64 for drafts.

if RENDERER == "raytracer":
    SHOW_VIEWER = False
    CAMERA_GUI  = True
elif RENDERER == "rasterizer":
    SHOW_VIEWER = True
    CAMERA_GUI  = False
RECORD_PATH   = "water.mp4"
RENDER_EVERY  = 2        # render (and record) every Nth sim step
VIDEO_FPS     = 50       # dt=1e-2, RENDER_EVERY=2 -> ~real-time playback

# --- particle export for Blender rendering ---
SAVE_PARTICLES = False   # 입자 저장 (물 없으면 False)
SAVE_CUP = True          # 컵 자세 저장 (궤적 생성용)
NO_WATER = True   # 궤적만 뽑을 때 True (물 엔티티 제외 -> 훨씬 빠름)
SAVE_DIR = os.path.expanduser("~/water_cup/traj_curveG_only")

# Cup geometry (meters)
CUP_R, CUP_H, WALL = 0.035, 0.10, 0.005     # outer radius / height / wall thickness
CUP_POS   = (0.55, 0.00, 0.001)             # cup base center, resting on the plane

# Simulation. Substep dt (DT/SUBSTEPS) must stay below the SPH stable timestep
# (~5.1e-4 for these water params/particle size), so use 80 substeps -> 5e-4.
DT, SUBSTEPS = 4e-3, 40

# Derived cup quantities
INNER_R  = CUP_R - WALL
INNER_H  = CUP_H - WALL
WATER_R  = INNER_R - 0.0005                   # water column radius (just inside the wall)
FILL_H   = FILL_FRACTION * INNER_H

# Franka end-effector poses (hand-link targets). For a SIDE grasp the gripper
# points horizontally (approach axis +X, toward the cup) instead of straight down.
Z_LIFT      = 0.25                           # lift height for the shake (raise for more
                                             # drama/clearance, at the cost of horizontal reach)
FINGER_OPEN  = 0.04
FINGER_GRASP = max(0.0, CUP_R - 0.003)       # close fingers to just around the cup

# Side-grasp geometry: the hand reaches in +X and grips the cup body at mid-height;
# the two fingers close on the cup's +/-Y faces (same grasp as main_pour.py).
GRASP_REACH   = 0.10                         # hand-frame origin sits this far back (-X) from cup center
GRASP_Z       = 0.07                         # hand height while gripping the side of the cup body
PREGRASP_BACK = 0.12                         # extra -X standoff for the open-finger straight-in approach
GRASP_X       = CUP_POS[0] - GRASP_REACH
PREGRASP_X    = GRASP_X - PREGRASP_BACK


def make_cup_obj(path):
    """Generate a watertight, open-top cup by revolving an L-shaped profile."""
    profile = np.array([
        [0.0,           0.0],
        [CUP_R,         0.0],
        [CUP_R,         CUP_H],
        [INNER_R,       CUP_H],
        [INNER_R,       WALL],
        [0.0,           WALL],
        [0.0,           0.0],
    ])
    cup = trimesh.creation.revolve(profile, sections=64)
    cup.export(path)


def downward_quat(tilt_deg=0.0, axis="x"):
    """Gripper-down quaternion (w,x,y,z), optionally tilted to induce pouring."""
    base = R.from_quat([1.0, 0.0, 0.0, 0.0])          # (x,y,z,w) == 180deg about x
    rot = R.from_euler(axis, tilt_deg, degrees=True) * base if tilt_deg else base
    x, y, z, w = rot.as_quat()
    return np.array([w, x, y, z])


def side_quat(tilt_deg=0.0):
    """Horizontal side-grasp orientation (w,x,y,z): approach +X, fingers on +/-Y.

    Optionally rocked by `tilt_deg` about the world X axis so the cup rocks over
    its +/-Y rim during a shake (matches the lateral Y sloshing). tilt_deg=0 gives
    the plain side grip, identical to downward_quat(-90, axis="y").
    """
    base = R.from_euler("y", -90, degrees=True) * R.from_quat([1.0, 0.0, 0.0, 0.0])
    rot = R.from_euler("x", tilt_deg, degrees=True) * base if tilt_deg else base
    x, y, z, w = rot.as_quat()
    return np.array([w, x, y, z])


def main():
    gs.init(backend=gs.gpu, precision="32", logging_level="warning")

    cup_obj = os.path.expanduser("~/water_cup/genesis_cup.obj")
    make_cup_obj(cup_obj)

    # ------------------------------------------------------------------ scene
    scene_kwargs = dict(
        sim_options=gs.options.SimOptions(dt=DT, substeps=SUBSTEPS),
        sph_options=gs.options.SPHOptions(
            pressure_solver="DFSPH",
            particle_size=PARTICLE_SIZE,
            lower_bound=(-0.2, -0.6, -0.02),          # roomy: shaking flings water far
            upper_bound=(1.2, 0.6, 0.7),
        ),
        viewer_options=gs.options.ViewerOptions(
            camera_pos=(1.4, -0.6, 0.6),
            camera_lookat=(0.55, 0.05, 0.18),
            camera_fov=35,
        ),
        vis_options=gs.options.VisOptions(visualize_sph_boundary=False),
    )
    if RENDERER == "raytracer":
        # Path-traced renderer: HDRI environment (reflections + soft fill light)
        # wrapped around the scene as an emissive sky sphere, plus one bright
        # sphere light as a key. This is what gives glass/water real refraction.
        scene_kwargs["renderer"] = gs.renderers.RayTracer(
            env_surface=gs.surfaces.Emission(
                emissive_texture=gs.textures.ImageTexture(image_path="textures/indoor_bright.png"),
            ),
            env_radius=12.0,
            #lights=[{"pos": (0.8, -0.4, 1.8), "radius": 0.4, "color": (12.0, 12.0, 12.0)}],
            lights=[{"pos": (0.8, -0.4, 1.8), "radius": 0.4, "color": (20.0, 20.0, 20.0)}]
        )
    scene = gs.Scene(**scene_kwargs)

    # Surfaces depend on the renderer: under the ray tracer, Glass/Water carry
    # real transmission + IOR (refraction); under the rasterizer they'd render
    # opaque, so we fall back to a translucent plastic stand-in there.
    if RENDERER == "raytracer":
        #cup_surface   = gs.surfaces.Glass(color=(0.95, 0.97, 1.0), roughness=0.03, ior=1.5)
        cup_surface = gs.surfaces.Smooth(color=(0.9, 0.93, 1.0, 0.05))
        #water_surface = gs.surfaces.Water(ior=1.33, vis_mode=WATER_VIS_MODE)   # real water IOR, transmissive
        water_surface = gs.surfaces.Glass(color=(0.85, 0.92, 1.0, 0.3), roughness=0.0, ior=1.33, vis_mode=WATER_VIS_MODE)
    else:
        cup_surface   = gs.surfaces.Smooth(color=(0.85, 0.88, 0.95, 0.35))               # glossy glass-ish
        water_surface = gs.surfaces.Smooth(color=(0.25, 0.55, 0.95, 0.6), vis_mode=WATER_VIS_MODE)

    # ----------------------------------------------------------------- entities
    plane = scene.add_entity(gs.morphs.Plane())

    cup = scene.add_entity(
        material=gs.materials.Rigid(
            needs_coup=True,            # participate in SPH<->rigid coupling (default True)
            coup_friction=0.0,
            coup_restitution=0.0,
            sdf_cell_size=0.002,        # < WALL so the thin cup wall is resolved
        ),
        morph=gs.morphs.Mesh(
            file=cup_obj,
            pos=CUP_POS,
            fixed=False,                # cup is free to be picked up
            convexify=False,            # keep the hollow, non-convex shape
            decimate=False,             # preserve wall geometry
        ),
        surface=cup_surface,
    )

    if NO_WATER:
        water = None
    else:
        water = scene.add_entity(
            material=gs.materials.SPH.Liquid(rho=1000.0, mu=0.0005, gamma=0.01, sampler="pbs"),
            morph=gs.morphs.Cylinder(
                pos=(CUP_POS[0], CUP_POS[1], CUP_POS[2] + WALL + FILL_H / 2.0),
                radius=WATER_R,
                height=FILL_H,
            ),
            surface=water_surface,
        )

    franka = scene.add_entity(gs.morphs.MJCF(file="xml/franka_emika_panda/panda.xml"))

    cam = scene.add_camera(res=(1280, 720), pos=(1.4, -0.6, 0.6),
                           lookat=(0.55, 0.05, 0.18), fov=35, GUI=True, spp=SPP)

    scene.build()
    # --- particle export setup ---
    if SAVE_PARTICLES or SAVE_CUP:
        os.makedirs(SAVE_DIR, exist_ok=True)
        np.save(os.path.join(SAVE_DIR, "meta.npy"), {
            "particle_size": PARTICLE_SIZE,
            "dt": DT,
            "render_every": RENDER_EVERY,
            "fps": VIDEO_FPS,
            "cup_r": CUP_R, "cup_h": CUP_H, "wall": WALL,
        })

    # --------------------------------------------------------------- robot setup
    motors_dof, fingers_dof = np.arange(7), np.arange(7, 9)
    franka.set_dofs_kp(np.array([4500, 4500, 3500, 3500, 2000, 2000, 2000, 100, 100]))
    franka.set_dofs_kv(np.array([450, 450, 350, 350, 200, 200, 200, 10, 10]))
    franka.set_dofs_force_range(
        np.array([-87, -87, -87, -87, -12, -12, -12, -100, -100]),
        np.array([87, 87, 87, 87, 12, 12, 12, 100, 100]),
    )

    ee = franka.get_link("hand")
    rigid = scene.sim.rigid_solver
    link_cup = cup.base_link.idx
    link_ee = ee.idx

    home = np.array([0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785, FINGER_OPEN, FINGER_OPEN])
    franka.set_dofs_position(home)
    franka.control_dofs_position(home)

    # --------------------------------------------------------------- helpers
    def to_np(x):
        return x.cpu().numpy() if hasattr(x, "cpu") else np.asarray(x)
    
    frame = {"i": 0, "saved": 0, "save_on": False}

    def sim_step():
        scene.step()
        if frame["i"] % RENDER_EVERY == 0:
            cam.render()
            if (SAVE_PARTICLES or SAVE_CUP) and frame["save_on"]:
                idx = frame["saved"]
                if SAVE_PARTICLES and water is not None:
                    pts = to_np(water.get_particles_pos())
                    np.save(os.path.join(SAVE_DIR, f"particles_{idx:04d}.npy"), pts)
                cup_pose = np.concatenate([to_np(cup.get_pos()), to_np(cup.get_quat())])
                np.save(os.path.join(SAVE_DIR, f"cup_{idx:04d}.npy"), cup_pose)
                frame["saved"] += 1
        frame["i"] += 1

    def settle(n):
        for _ in range(n):
            sim_step()

    # start beside the cup (open-finger standoff for the straight-in side grasp)
    cur = {"pos": np.array([PREGRASP_X, CUP_POS[1], GRASP_Z], dtype=float)}

    def move_lin(target_pos, quat, n_steps, finger):
        """Cartesian straight-line servo via per-step IK; controls accel via n_steps.

        Each waypoint's IK is seeded from the arm's current config (init_qpos) with
        max_samples=1, so consecutive solves stay on one IK branch. Without this the
        default 50-sample random restart can return a different branch near the
        horizontal-wrist reach, and the stiff PD snaps the (welded) cup to it --
        flinging the water out on the lift, before the shake even starts.
        """
        target_pos = np.asarray(target_pos, dtype=float)
        start = cur["pos"].copy()
        n = max(1, int(n_steps))
        for k in range(1, n + 1):
            a = k / n
            p = (1 - a) * start + a * target_pos
            q_seed = franka.get_dofs_position()
            q_seed = q_seed.cpu().numpy() if hasattr(q_seed, "cpu") else np.asarray(q_seed, float)
            q = franka.inverse_kinematics(link=ee, pos=p, quat=quat,
                                          init_qpos=q_seed, max_samples=1)
            franka.control_dofs_position(q[:-2], motors_dof)
            franka.control_dofs_position(np.array([finger, finger]), fingers_dof)
            sim_step()
        cur["pos"] = target_pos

    def move_lin_tilt(target_pos, n_steps, finger, tilt_deg, tilt_period):
        """직선 이동 + 손목 좌우 기울기 진동. 시작/끝은 기울기 0으로 램프."""
        target_pos = np.asarray(target_pos, dtype=float)
        start = cur["pos"].copy()
        n = max(1, int(n_steps))
        ramp = max(1.0, 0.15 * n)
        for k in range(1, n + 1):
            a = k / n
            p = (1 - a) * start + a * target_pos
            env = min(1.0, k / ramp, (n - k) / ramp)
            env = max(0.0, env)
            tilt = env * tilt_deg * np.sin(2.0 * np.pi * k / tilt_period)
            q_seed = franka.get_dofs_position()
            q_seed = q_seed.cpu().numpy() if hasattr(q_seed, "cpu") else np.asarray(q_seed, float)
            q = franka.inverse_kinematics(link=ee, pos=p, quat=side_quat(tilt),
                                          init_qpos=q_seed, max_samples=1)
            franka.control_dofs_position(q[:-2], motors_dof)
            franka.control_dofs_position(np.array([finger, finger]), fingers_dof)
            sim_step()
        cur["pos"] = target_pos

    def move_lin_wave(target_pos, quat, n_steps, finger, wave_amp=0.35, wave_cycles=2.0):
        """직선 이동 + 진행 속도에 사인 변조.

        경로는 직선이지만 진행률에 sin을 더해 중간에 가속/감속이 반복됩니다.
        wave_amp   : 변조 세기 (0이면 기존 move_lin과 동일, 0.35 권장)
        wave_cycles: 이동 구간 동안의 속도 진동 횟수
        시작과 끝에서는 변조가 0이라 위치가 정확히 맞습니다.
        """
        target_pos = np.asarray(target_pos, dtype=float)
        start = cur["pos"].copy()
        n = max(1, int(n_steps))
        for k in range(1, n + 1):
            u = k / n
            u = u*u*u                              # 3차: 가속도가 점점 커짐 (초반 매우 느림)
            a = u + wave_amp * np.sin(2.0 * np.pi * wave_cycles * u) / (2.0 * np.pi * wave_cycles)
            a = min(1.0, max(0.0, a))
            p = (1 - a) * start + a * target_pos
            q_seed = franka.get_dofs_position()
            q_seed = q_seed.cpu().numpy() if hasattr(q_seed, "cpu") else np.asarray(q_seed, float)
            q = franka.inverse_kinematics(link=ee, pos=p, quat=quat,
                                          init_qpos=q_seed, max_samples=1)
            franka.control_dofs_position(q[:-2], motors_dof)
            franka.control_dofs_position(np.array([finger, finger]), fingers_dof)
            sim_step()
        cur["pos"] = target_pos

    def shake(center, finger):
        """Drive a violent lateral (+optional vertical/tilt) oscillation about `center`.

        The cup is held in the side grasp, so `center` is the hand's lifted pose and
        the base orientation is the horizontal `side` grip. Each step commands a
        sinusoidal pose; the high accelerations are what slosh the water over the
        rim. An amplitude envelope ramps the vigor up over the first cycle and back
        down over the last so the hand returns centered and upright for the set-down
        (no terminal jerk).

        Every IK call is seeded from the centered lifted config (init_qpos=q_ref)
        with max_samples=1, so the redundant arm never random-restarts onto a
        different IK branch mid-shake -- which would teleport the welded cup.
        """
        center = np.asarray(center, dtype=float)
        q_ref = franka.get_dofs_position()
        q_ref = q_ref.cpu().numpy() if hasattr(q_ref, "cpu") else np.asarray(q_ref, float)
        total = SHAKE_CYCLES * SHAKE_PERIOD
        ramp = SHAKE_PERIOD
        for k in range(total + 1):
            # ramp 0->1 over the first cycle, hold, then 1->0 over the last cycle
            env = min(1.0, k / ramp, (total - k) / ramp)
            env = max(0.0, env)
            phase = 2.0 * np.pi * k / SHAKE_PERIOD
            p = center.copy()
            p[1] += env * SHAKE_AMP_Y * np.sin(phase)
            p[2] += env * SHAKE_AMP_Z * np.sin(2.0 * phase)   # bob twice per lateral swing
            tilt = env * SHAKE_TILT * np.sin(phase)           # rock over the +/-Y rim in the swing dir
            q = side_quat(tilt)
            ik = franka.inverse_kinematics(
                link=ee, pos=p, quat=q,
                init_qpos=q_ref,   # seed from the centered grasp -> stay on one IK branch
                max_samples=1,     # no random branch-hop mid-shake
            )
            franka.control_dofs_position(ik[:-2], motors_dof)
            franka.control_dofs_position(np.array([finger, finger]), fingers_dof)
            sim_step()
        cur["pos"] = center

    def settle_at(target, tol=1e-2, vel_tol=1e-2, max_steps=60):
        """Hold a joint target until the arm actually arrives and stops (or times out)."""
        target = target.cpu().numpy() if hasattr(target, "cpu") else np.asarray(target, float)
        franka.control_dofs_position(target)   
        for _ in range(max_steps):
            sim_step()
            pos_err = np.abs(franka.get_dofs_position().cpu().numpy() - target)
            speed = np.abs(franka.get_dofs_velocity().cpu().numpy())
            if pos_err.max() < tol and speed.max() < vel_tol:  # arrived and at rest
                return
        print(f"[warn] settle_at did not converge (max joint err {pos_err.max():.4f} rad)")


    def move_line(pos, quat, fingers, num_waypoints=100):
        """Move the end effector in a straight Cartesian line to pos at the given orientation."""
        start_pos = ee.get_pos().cpu().numpy()
        pos = np.asarray(pos, float)
        q = None
        # interpolate the EE position in a straight line, solving IK at each waypoint
        for p in np.linspace(start_pos, pos, num_waypoints):
            q = franka.inverse_kinematics(link=ee, pos=p, quat=quat)
            q[-2:] = fingers
            franka.control_dofs_position(q)
            sim_step()
        settle_at(q)

    side = side_quat()          # horizontal gripper: approach +X, fingers on +/-Y

    # ------------------------------------------------------------- sequence
    cam.start_recording()

    # 1) let the water settle in the cup
    for _ in range(int(1.5 / DT)):
        scene.step()

    # 2) approach to a standoff beside the cup (collision-aware), gripper open
    pregrasp_q = franka.inverse_kinematics(
        link=ee, pos=cur["pos"], quat=side)
    pregrasp_q[-2:] = FINGER_OPEN
    path = franka.plan_path(qpos_goal=pregrasp_q, num_waypoints=180)
    for wp in path:
        franka.control_dofs_position(wp)
        sim_step()
    settle(10)

    # 3) move straight in (+X) so the open fingers straddle the cup body
    move_lin((GRASP_X, CUP_POS[1], GRASP_Z), side, 60, FINGER_OPEN)
    settle(10)

    # 4) close the gripper (visual) and weld the cup to the hand
    for _ in range(10):
        franka.control_dofs_position(np.array([FINGER_GRASP, FINGER_GRASP]), fingers_dof)
        sim_step()
    rigid.add_weld_constraint(link_cup, link_ee)


    # lift -> 수평(+Y로 옆 이동) -> 내려놓기
    move_lin((GRASP_X, CUP_POS[1], Z_LIFT), side, 350, FINGER_GRASP)
    settle(600)
    frame["save_on"] = True
    import math as _m
    # 접선 등가속(u^2) + 진행할수록 조여지는 곡선 -> 횡가속이 매끄럽게 증가
    _N = 40
    for _k in range(1, _N + 1):
        _u = _k / float(_N)
        _p = _u * _u                                  # 등가속
        _y = 0.38 * _p
        _amp = 0.05 + 0.10 * _p                       # 곡률을 점점 크게
        _x = GRASP_X + _amp * _m.sin(_m.pi * _p)
        move_lin((_x, _y, Z_LIFT), side, 6, FINGER_GRASP)
    settle(20)
    move_lin((GRASP_X, 0.38, GRASP_Z + 0.005), side, 200, FINGER_GRASP)

    frame["save_on"] = False

    # 8) release: remove the weld and open the gripper
    rigid.delete_weld_constraint(link_cup, link_ee)
    for _ in range(40):
        franka.control_dofs_position(np.array([FINGER_OPEN, FINGER_OPEN]), fingers_dof)
        sim_step()

    # 9) retreat straight back (-X) and let everything settle so the spill is visible
    move_lin((PREGRASP_X, CUP_POS[1], GRASP_Z), side, 100, FINGER_OPEN)
    settle(int(0.5 / DT))

    cam.stop_recording(save_to_filename=RECORD_PATH, fps=VIDEO_FPS)
    print(f"Saved {RECORD_PATH}")


if __name__ == "__main__":
    main()