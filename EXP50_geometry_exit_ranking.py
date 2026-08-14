"""
EXP50 — Exit-Risk Ranking Transport Decomposition.

Replays the exact frozen EXP49 backbone/model and tests whether the original
TRAIN-fitted JOINT4_EXIT geometry model robustly ranks EXIT risk within each
frozen direction×time environment and each fixed horizon.

Formal target:
    8 environments × 4 horizons = 32 mandatory AUC cells.
    PASS only if every cell is scorable and the 95% whole-BRT-day bootstrap
    lower CI bound for AUC is > 0.5.

This does NOT recalibrate probabilities and does NOT rescue EXP49.
Historical OOS is repeatedly inspected. Exp27 remains untouched.
"""

from pathlib import Path
import contextlib
import io
import runpy
import time

import numpy as np
import pandas as pd

BOOT_REPS = 10_000
MIN_VALID_BOOT = 9_500
SEED = 50_000
AUC_NULL = 0.5

t0 = time.perf_counter()

HERE = Path(__file__).resolve().parent
EXP49_PATH = HERE / "EXP49_symmetric_boundary_timing.py"

if not EXP49_PATH.exists():
    raise FileNotFoundError(
        f"Required frozen EXP49 runner not found: {EXP49_PATH}"
    )

buf = io.StringIO()

try:
    with contextlib.redirect_stdout(buf):
        ctx = runpy.run_path(
            str(EXP49_PATH),
            run_name="__exp49_replay__",
        )
except Exception:
    replay = buf.getvalue().splitlines()
    print("=" * 132)
    print("EXP50 ABORT — EXP49 REPLAY FAILED")
    print("=" * 132)
    print("\n".join(replay[-80:]))
    raise

required_names = (
    "timing",
    "JOINT_ENVS",
    "HORIZONS",
    "joint_identifiable",
    "all_scorable",
    "formal_status",
)

missing = [
    name
    for name in required_names
    if name not in ctx
]

if missing:
    raise RuntimeError(
        f"EXP50 missing required frozen EXP49 objects: {missing}"
    )

timing = ctx["timing"].copy()
JOINT_ENVS = tuple(ctx["JOINT_ENVS"])
HORIZONS = tuple(ctx["HORIZONS"])

if not bool(ctx["joint_identifiable"]):
    raise RuntimeError(
        "EXP50 ABORT: frozen EXP49 JOINT4 identifiability did not reproduce."
    )

if not bool(ctx["all_scorable"]):
    raise RuntimeError(
        "EXP50 ABORT: frozen EXP49 environment scorability did not reproduce."
    )

if str(ctx["formal_status"]) != "FAIL":
    raise RuntimeError(
        "EXP50 ABORT: expected frozen EXP49 formal status FAIL."
    )

needed_cols = {
    "joint_env",
    "horizon",
    "brt_date",
    "y_exit",
    "p_base_exit",
    "p_joint4_exit",
}

missing_cols = needed_cols.difference(timing.columns)

if missing_cols:
    raise RuntimeError(
        f"EXP50 missing frozen timing columns: {sorted(missing_cols)}"
    )

if len(JOINT_ENVS) != 8:
    raise RuntimeError(
        f"EXP50 expected 8 frozen environments, got {len(JOINT_ENVS)}"
    )

if HORIZONS != (15, 30, 60, 120):
    raise RuntimeError(
        f"EXP50 horizon reproduction failed: {HORIZONS}"
    )

print("=" * 132)
print("EXP50 — EXIT-RISK RANKING TRANSPORT DECOMPOSITION")
print("=" * 132)
print("Frozen EXP49 replay = PASS")
print("EXP49_JOINT4_IDENTIFIABILITY = PASS")
print("EXP49_FORMAL_STATUS = PRESERVED_FAIL")
print("EXP47_ROBUST_MINIMAL_CORRIDOR_EQUATION_STATUS = PRESERVED_PASS")
print("EXP27 = UNTOUCHED")
print("RUNTIME_PROMOTION = NONE")


def auc_unweighted(y, score):
    y = np.asarray(y, int)
    score = np.asarray(score, float)

    n1 = int((y == 1).sum())
    n0 = int((y == 0).sum())

    if n1 == 0 or n0 == 0:
        return np.nan

    order = np.argsort(score, kind="mergesort")
    ys = y[order]
    ss = score[order]

    total = 0.0
    neg_before = 0.0

    i = 0
    n = len(y)

    while i < n:
        j = i + 1
        while j < n and ss[j] == ss[i]:
            j += 1

        block_y = ys[i:j]
        pos = float((block_y == 1).sum())
        neg = float((block_y == 0).sum())

        total += pos * (neg_before + 0.5 * neg)
        neg_before += neg
        i = j

    return float(total / (n1 * n0))


def prepare_weighted_auc_structure(q):
    y = q["y_exit"].to_numpy(int)
    score = q["p_joint4_exit"].to_numpy(float)

    if not np.isfinite(score).all():
        raise RuntimeError("EXP50 non-finite JOINT4 scores.")

    days = pd.Index(sorted(pd.unique(q["brt_date"])))
    day_to_idx = {d: i for i, d in enumerate(days)}
    day_idx = np.array(
        [day_to_idx[d] for d in q["brt_date"].to_numpy()],
        dtype=int,
    )

    unique_scores, group_idx = np.unique(
        score,
        return_inverse=True,
    )

    d = len(days)
    g = len(unique_scores)

    pos_day_group = np.zeros((d, g), float)
    neg_day_group = np.zeros((d, g), float)

    np.add.at(
        pos_day_group,
        (day_idx[y == 1], group_idx[y == 1]),
        1.0,
    )
    np.add.at(
        neg_day_group,
        (day_idx[y == 0], group_idx[y == 0]),
        1.0,
    )

    return {
        "days": days,
        "pos_day_group": pos_day_group,
        "neg_day_group": neg_day_group,
    }


def whole_day_auc_bootstrap(q, seed):
    y = q["y_exit"].to_numpy(int)
    score = q["p_joint4_exit"].to_numpy(float)

    point = auc_unweighted(y, score)

    prep = prepare_weighted_auc_structure(q)

    pos_dg = prep["pos_day_group"]
    neg_dg = prep["neg_day_group"]

    n_days = pos_dg.shape[0]

    if n_days < 2:
        return {
            "point": point,
            "lo": np.nan,
            "hi": np.nan,
            "valid": 0,
            "days": n_days,
        }

    rng = np.random.default_rng(seed)
    probs = np.full(n_days, 1.0 / n_days, float)

    aucs = []
    chunk_size = 500
    produced = 0

    while produced < BOOT_REPS:
        batch = min(chunk_size, BOOT_REPS - produced)

        day_mult = rng.multinomial(
            n_days,
            probs,
            size=batch,
        ).astype(float)

        pos = day_mult @ pos_dg
        neg = day_mult @ neg_dg

        total_pos = pos.sum(axis=1)
        total_neg = neg.sum(axis=1)

        valid = (
            (total_pos > 0.0)
            &
            (total_neg > 0.0)
        )

        if valid.any():
            pv = pos[valid]
            nv = neg[valid]

            neg_before = (
                np.cumsum(nv, axis=1)
                -
                nv
            )

            u = np.sum(
                pv
                *
                (
                    neg_before
                    +
                    0.5 * nv
                ),
                axis=1,
            )

            auc = (
                u
                /
                (
                    total_pos[valid]
                    *
                    total_neg[valid]
                )
            )

            aucs.append(auc)

        produced += batch

    boot = (
        np.concatenate(aucs)
        if aucs
        else np.empty(0, float)
    )

    if len(boot) == 0:
        lo = np.nan
        hi = np.nan
    else:
        lo = float(np.quantile(boot, 0.025))
        hi = float(np.quantile(boot, 0.975))

    return {
        "point": float(point),
        "lo": lo,
        "hi": hi,
        "valid": int(len(boot)),
        "days": int(n_days),
    }


print()
print("=" * 132)
print("EXP50 FROZEN CELL SCORABILITY / POINT REPRODUCTION")
print("=" * 132)

cell_rows = []
all_cells_scorable = True

for env_index, env in enumerate(JOINT_ENVS, start=1):
    print()
    print(env)

    for h_index, horizon in enumerate(HORIZONS, start=1):
        q = (
            timing.loc[
                timing["joint_env"].eq(env)
                &
                timing["horizon"].eq(horizon)
            ]
            .copy()
            .reset_index(drop=True)
        )

        n = len(q)
        n_exit = int(q["y_exit"].sum())
        n_no = int(n - n_exit)
        days = int(q["brt_date"].nunique())

        base_auc = auc_unweighted(
            q["y_exit"].to_numpy(int),
            q["p_base_exit"].to_numpy(float),
        )

        joint_auc = auc_unweighted(
            q["y_exit"].to_numpy(int),
            q["p_joint4_exit"].to_numpy(float),
        )

        scorable = bool(
            n_exit > 0
            and n_no > 0
            and days >= 2
            and np.isfinite(joint_auc)
            and np.isfinite(base_auc)
        )

        if scorable and abs(base_auc - 0.5) > 1e-12:
            raise RuntimeError(
                f"EXP50 BASE AUC reproduction failed "
                f"{env} H={horizon}: {base_auc}"
            )

        all_cells_scorable = all_cells_scorable and scorable

        print(
            f"  H={horizon:>3}m "
            f"n={n:>4} EXIT={n_exit:>4} NO_EXIT={n_no:>4} "
            f"days={days:>3} "
            f"AUC_BASE={base_auc:.6f} "
            f"AUC_JOINT4={joint_auc:.6f} "
            f"SCORABLE={scorable}"
        )

        cell_rows.append(
            {
                "env": env,
                "horizon": horizon,
                "n": n,
                "exit": n_exit,
                "no_exit": n_no,
                "days": days,
                "base_auc": base_auc,
                "joint_auc": joint_auc,
                "scorable_preboot": scorable,
                "seed": (
                    SEED
                    +
                    env_index * 1000
                    +
                    h_index
                ),
            }
        )

print()
print(
    "EXP50_PREBOOT_CELL_STATUS =",
    "PASS" if all_cells_scorable else "UNDERPOWERED_RANKING_CELL",
)

print()
print("=" * 132)
print("EXP50 PRIMARY WHOLE-BRT-DAY AUC INFERENCE")
print("Formal null per environment×horizon: AUC = 0.5")
print("PASS requires CI95 lower bound > 0.5 in all 32 cells")
print("=" * 132)

formal_pass = bool(all_cells_scorable)
result_rows = []

for item in cell_rows:
    env = item["env"]
    horizon = item["horizon"]

    q = (
        timing.loc[
            timing["joint_env"].eq(env)
            &
            timing["horizon"].eq(horizon)
        ]
        .copy()
        .reset_index(drop=True)
    )

    if not item["scorable_preboot"]:
        formal_pass = False

        result = {
            "point": item["joint_auc"],
            "lo": np.nan,
            "hi": np.nan,
            "valid": 0,
            "days": item["days"],
        }

        passed = False
        boot_scorable = False

    else:
        result = whole_day_auc_bootstrap(
            q,
            item["seed"],
        )

        boot_scorable = bool(
            result["valid"] >= MIN_VALID_BOOT
        )

        passed = bool(
            boot_scorable
            and
            np.isfinite(result["lo"])
            and
            result["lo"] > AUC_NULL
        )

        formal_pass = (
            formal_pass
            and
            passed
        )

    obs = float(q["y_exit"].mean())
    mean_p = float(q["p_joint4_exit"].mean())
    cal_gap = float(mean_p - obs)

    print(
        f"{env:<31} "
        f"H={horizon:>3}m "
        f"AUC={result['point']:.6f} "
        f"CI95=[{result['lo']:.6f},{result['hi']:.6f}] "
        f"valid_boot={result['valid']:>5}/{BOOT_REPS} "
        f"obsEXIT={obs:.4f} "
        f"meanP={mean_p:.4f} "
        f"cal_gap(P-obs)={cal_gap:+.4f} "
        f"PASS={passed}"
    )

    result_rows.append(
        {
            **item,
            **result,
            "boot_scorable": boot_scorable,
            "pass": passed,
            "obs_exit": obs,
            "mean_p": mean_p,
            "cal_gap": cal_gap,
        }
    )

results = pd.DataFrame(result_rows)

n_pass = int(results["pass"].sum())
all_boot_scorable = bool(results["boot_scorable"].all())

ranking_status = bool(
    formal_pass
    and n_pass == 32
    and all_boot_scorable
    and bool(ctx["joint_identifiable"])
)

print()
print("=" * 132)
print("EXP50 DESCRIPTIVE HETEROGENEITY — DIAGNOSTIC ONLY")
print("=" * 132)

for env in JOINT_ENVS:
    q = results.loc[
        results["env"].eq(env)
    ]

    print(
        f"{env:<31} "
        f"AUC range={q['point'].min():.4f}–{q['point'].max():.4f} "
        f"cal_gap range={q['cal_gap'].min():+.4f}–{q['cal_gap'].max():+.4f}"
    )

print()
print("=" * 132)
print("EXP50 FORMAL VERDICT")
print("=" * 132)

print(
    "EXP50_RANKING_CELL_STATUS =",
    (
        "PASS"
        if all_boot_scorable and all_cells_scorable
        else
        "UNDERPOWERED_RANKING_CELL"
    ),
)

print(
    "EXP50_FORMAL_CELLS_PASS =",
    f"{n_pass}/32",
)

status = (
    "PASS"
    if ranking_status
    else
    (
        "UNDERPOWERED_RANKING_CELL"
        if not all_boot_scorable or not all_cells_scorable
        else
        "FAIL"
    )
)

print("GEOMETRY_EXIT_RANKING_TRANSPORT =", status)
print("ROBUST_EXIT_URGENCY_ORDERING =", status)
print("EXP50_FORMAL_STATUS =", status)

print("EXP49_TIMING_GEOMETRY_FAMILY_STATUS = PRESERVED_FAIL")
print("EXP49_JOINT4_IDENTIFIABILITY_STATUS = PRESERVED_PASS")
print("EXP48_POSITION_EXIT_CLOCK_STATUS = PRESERVED_FAIL")
print("EXP47_ROBUST_MINIMAL_CORRIDOR_EQUATION_STATUS = PRESERVED_PASS")
print("EXP45_ROBUST_WHICH_SIDE_LAW_STATUS = PRESERVED_PASS")
print("EXP44_ROBUST_POSITION_CORE_STATUS = PRESERVED_PASS")
print("EXP27 = UNTOUCHED")
print("RUNTIME_PROMOTION = NONE")

print()
print("=" * 132)
print("FROZEN INTERPRETATION RULES")
print("=" * 132)

rules = [
    "1) Exp50 decomposes discrimination/ranking from calibration after Exp49; it is not a new predictor search.",
    "2) The exact frozen Exp49 program is replayed first; any reproduction failure aborts before Exp50 scoring.",
    "3) The model is the original TRAIN-fitted JOINT4_EXIT unchanged.",
    "4) Target is EXIT by fixed H vs NO_EXIT by fixed H.",
    "5) Primary metric is ROC AUC within each fixed environment and fixed horizon.",
    "6) BASE_EXIT has AUC=0.5 within a fixed horizon because it is constant across states; formal null is 0.5.",
    "7) There are 8 environments × 4 horizons = 32 mandatory formal cells.",
    "8) Whole contributing BRT days are resampled with replacement; selected-day multiplicity is preserved.",
    "9) Weighted ROC AUC gives 0.5 credit to tied scores.",
    "10) Cell scorability requires both classes, >=2 BRT days, and >=9500/10000 valid bootstrap replicates.",
    "11) Formal cell PASS requires CI95 lower bound >0.5.",
    "12) GEOMETRY_EXIT_RANKING_TRANSPORT and ROBUST_EXIT_URGENCY_ORDERING require 32/32.",
    "13) Calibration gaps and heterogeneity are diagnostic only and cannot rescue a ranking failure.",
    "14) Exp50 PASS would establish ranking/urgency ordering only, not calibrated P(EXIT), exact timing, or reversal of Exp49 FAIL.",
    "15) No pooled-horizon replacement, dropped horizon/environment, recalibration, refit, threshold, alternate subset/transform or new feature.",
    "16) No Validation/TEST refit and no Exp27 scoring/modification.",
    "17) Historical OOS is repeatedly inspected; fresh-forward Exp27 remains required before runtime promotion.",
]

for line in rules:
    print(line)

print()
print(f"FINALIZADO em {time.perf_counter()-t0:.2f}s")
