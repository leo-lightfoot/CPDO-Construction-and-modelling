# =========================================================
# CPDO WITH DATA-DRIVEN CRISIS (FINAL STABLE VERSION)
# =========================================================

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from dataclasses import dataclass


# =========================================================
# PARAMETERS
# =========================================================

@dataclass
class CIRParams:
    kappa: float
    theta: float
    sigma: float
    s0: float


@dataclass
class CrisisParams:
    p_low: float
    p_high: float
    threshold_spread: float
    jump_mean: float
    jump_std: float


@dataclass
class CPDOParams:
    target_nav: float = 100.0
    floor_nav: float = 10.0
    max_leverage: float = 15.0
    dv01: float = 0.0015
    management_fee: float = 0.003
    roll_cost_bps: float = 3.0
    roll_every_steps: int = 26
    recovery_rate: float = 0.4


# =========================================================
# CIR CALIBRATION
# =========================================================

def calibrate_cir(spreads, dt=1/252):

    s = spreads.dropna().reset_index(drop=True)

    s_t = s[:-1].values
    ds = s.diff().dropna().values

    X = np.vstack([np.ones_like(s_t), s_t]).T
    alpha, beta = np.linalg.lstsq(X, ds, rcond=None)[0]

    kappa = max(0.1, -beta / dt)
    theta = max(1, alpha / (kappa * dt))
    sigma = np.std(ds) / np.sqrt(dt)

    return CIRParams(kappa, theta, sigma, s.iloc[0])


# =========================================================
# DATA-DRIVEN CRISIS CALIBRATION (FIXED)
# =========================================================

def calibrate_crisis_model(spreads):

    spreads = spreads.dropna().reset_index(drop=True)

    # DAILY changes (no resampling!)
    dS = spreads.diff().dropna().reset_index(drop=True)

    spreads_aligned = spreads[:-1].reset_index(drop=True)

    abs_dS = np.abs(dS)

    # Slightly looser threshold for IG
    threshold = np.percentile(abs_dS, 90)

    crisis_mask = abs_dS >= threshold

    # Ensure we have enough crisis points
    if crisis_mask.sum() < 20:
        print("⚠️ Too few crisis points → forcing top 50 moves")
        top_idx = np.argsort(abs_dS)[-50:]
        crisis_mask = np.zeros_like(abs_dS, dtype=bool)
        crisis_mask[top_idx] = True

    # Jump distribution
    jump_sizes = dS[crisis_mask]

    jump_mean = jump_sizes.mean()
    jump_std = jump_sizes.std()

    if np.isnan(jump_mean) or np.isnan(jump_std):
        print("⚠️ Jump stats invalid → fallback")
        jump_mean = abs_dS.mean()
        jump_std = abs_dS.std()

    jump_std = max(jump_std, 1e-6)

    # State-dependent probability
    high_spread_threshold = spreads_aligned.quantile(0.8)
    high_regime = spreads_aligned > high_spread_threshold

    p_high = crisis_mask[high_regime].mean()
    p_low = crisis_mask[~high_regime].mean()

    # Safety
    if np.isnan(p_high):
        p_high = 0.05
    if np.isnan(p_low):
        p_low = 0.02

    p_high = max(p_high, 0.01)
    p_low = max(p_low, 0.005)

    print("\n=== Crisis Calibration ===")
    print(f"Num crisis points: {crisis_mask.sum()}")
    print(f"Jump mean: {jump_mean:.2f}")
    print(f"Jump std: {jump_std:.2f}")
    print(f"Low regime prob: {p_low:.4f}")
    print(f"High regime prob: {p_high:.4f}")
    print("=========================\n")

    return CrisisParams(
        p_low=p_low,
        p_high=p_high,
        threshold_spread=high_spread_threshold,
        jump_mean=jump_mean,
        jump_std=jump_std
    )


# =========================================================
# SPREAD SIMULATION
# =========================================================

def simulate_spread_paths(params, crisis_params, n_paths, T=10, dt=1/252, seed=42):

    n_steps = int(T / dt)
    paths = np.zeros((n_steps + 1, n_paths))
    paths[0] = params.s0

    rng = np.random.default_rng(seed)

    for t in range(n_steps):

        S = np.maximum(paths[t], 1e-6)

        dW = rng.standard_normal(n_paths) * np.sqrt(dt)

        drift = params.kappa * (params.theta - S) * dt
        diffusion = params.sigma * np.sqrt(S) * dW

        # Crisis regime
        p_jump = np.where(
            S > crisis_params.threshold_spread,
            crisis_params.p_high,
            crisis_params.p_low
        )

        jump_flag = rng.random(n_paths) < p_jump

        jump_size = jump_flag * rng.normal(
            crisis_params.jump_mean,
            crisis_params.jump_std,
            size=n_paths
        )

        dS = drift + diffusion + jump_size

        paths[t+1] = np.clip(np.nan_to_num(S + dS, nan=1e-6), 1e-6, 2000)

    return paths


# =========================================================
# CPDO SIMULATION
# =========================================================

def run_cpdo_simulation(spread_paths, cpdo_params, sofr_series, dt=1/252):

    n_steps, n_paths = spread_paths.shape[0] - 1, spread_paths.shape[1]

    nav = np.zeros((n_steps + 1, n_paths))
    nav[0] = 100

    leverage = np.zeros_like(nav)
    default = np.zeros(n_paths, dtype=bool)
    default_time = np.full(n_paths, np.nan)

    sofr_interp = np.interp(
        np.arange(n_steps),
        np.linspace(0, n_steps, len(sofr_series)),
        sofr_series
    )

    LGD = 1 - cpdo_params.recovery_rate
    rng = np.random.default_rng(123)

    for t in range(n_steps):

        S = spread_paths[t]
        dS = spread_paths[t+1] - S
        NAV = nav[t]

        alive = ~default
        NAV_safe = np.maximum(NAV, 1e-6)

        L = 1 + 5 * (cpdo_params.target_nav - NAV_safe) / cpdo_params.target_nav
        L = np.clip(L, 0, cpdo_params.max_leverage)
        leverage[t] = L

        exposure = L * NAV

        carry = exposure * (S / 10000) * dt
        mtm = -exposure * cpdo_params.dv01 * dS
        interest = sofr_interp[t] * NAV * dt
        fees = cpdo_params.management_fee * NAV * dt

        # Default
        lambda_t = (S / 10000) / LGD
        default_prob = 1 - np.exp(-lambda_t * dt)

        default_event = (rng.random(n_paths) < default_prob) & alive
        jump_loss = exposure * LGD * default_event

        roll_cost = 0
        if t % cpdo_params.roll_every_steps == 0 and t > 0:
            roll_cost = cpdo_params.roll_cost_bps * 1e-4 * exposure

        nav_next = NAV + carry + mtm + interest - fees - roll_cost - jump_loss

        nav[t+1] = np.nan_to_num(nav_next, nan=cpdo_params.floor_nav)

        newly_defaulted = (nav[t+1] <= cpdo_params.floor_nav) & alive
        default[newly_defaulted] = True
        default_time[newly_defaulted] = t * dt

        nav[t+1][default] = cpdo_params.floor_nav

    return nav, default, leverage, default_time


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    print("Loading data...")

    cdx = pd.read_csv("CDX IG CDSI GEN 5Y Corp(CDX IG CDSI GEN 5Y Corp).csv", sep=";")
    cdx.columns = ["Date", "Spread"]

    # 🔥 CRITICAL FIX: sort by date
    cdx["Date"] = pd.to_datetime(cdx["Date"])
    cdx = cdx.sort_values("Date")

    cdx["Spread"] = pd.to_numeric(cdx["Spread"], errors="coerce")
    spreads = cdx["Spread"].dropna()

    sofr = pd.read_csv("SOFR rates(Daily).csv", sep=";")
    sofr["SOFR"] = (
        sofr.iloc[:,1].astype(str).str.replace(",", ".", regex=False).astype(float)
    )
    sofr_series = (sofr["SOFR"] / 100).dropna().values

    cpdo_params = CPDOParams()

    print("\nCalibrating...\n")

    cir_params = calibrate_cir(spreads)
    crisis_params = calibrate_crisis_model(spreads)

    print("Simulating spreads...\n")

    spread_paths = simulate_spread_paths(
        cir_params,
        crisis_params,
        n_paths=10000
    )

    print("Running CPDO...\n")

    nav, default, leverage, default_time = run_cpdo_simulation(
        spread_paths, cpdo_params, sofr_series
    )

    nav = np.nan_to_num(nav, nan=cpdo_params.floor_nav)

    pd_est = np.mean(default)
    print(f"\n🔥 FINAL PD: {pd_est:.4f}")

    # =========================================================
    # PLOTS
    # =========================================================

    plt.figure()
    plt.plot(nav[:, :50])
    plt.title("NAV Paths")

    plt.figure()
    plt.plot(spread_paths[:, :50])
    plt.title("Spread Paths")

    plt.figure()
    plt.hist(nav[-1], bins=50)
    plt.title("Final NAV Distribution")

    plt.figure()
    plt.hist(default.astype(int), bins=2)
    plt.title("Default Occurrence")

    plt.figure()
    plt.plot(leverage[:, :50])
    plt.title("Leverage Paths")

    plt.figure()
    plt.hist(default_time[~np.isnan(default_time)], bins=50)
    plt.title("Time to Default")

    plt.show()