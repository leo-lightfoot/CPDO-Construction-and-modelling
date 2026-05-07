# =========================================================
# CPDO MONTE CARLO SIMULATION WITH VOLATILITY TESTING
# =========================================================

import numpy as np
import pandas as pd
from dataclasses import dataclass


# =========================================================
# PARAMETER CLASSES
# =========================================================

@dataclass
class JumpCIRParams:
    kappa: float
    theta: float
    sigma: float
    lam: float
    jump_sizes: np.ndarray
    s0: float


@dataclass
class CPDOParams:
    target_nav: float = 100.0
    floor_nav: float = 10.0
    max_leverage: float = 15.0
    dv01: float = 0.0005
    management_fee: float = 0.0025
    roll_cost_bps: float = 1.5
    roll_every_steps: int = 26


# =========================================================
# CALIBRATION
# =========================================================

def calibrate_jump_cir(spread_series, dt=1/52):

    s = pd.Series(spread_series).dropna().reset_index(drop=True)

    s_t = s[:-1].values
    ds = s.diff().dropna().values

    X = np.vstack([np.ones_like(s_t), s_t]).T
    alpha, beta = np.linalg.lstsq(X, ds, rcond=None)[0]

    kappa = -beta / dt
    theta = alpha / (kappa * dt)

    std_ds = np.std(ds)
    jump_mask = np.abs(ds) > 3 * std_ds

    residuals = ds - (alpha + beta * s_t)

    sigma = np.sqrt(np.mean((residuals**2) / (np.maximum(s_t, 1e-6) * dt)))

    jump_sizes = residuals[jump_mask]
    if len(jump_sizes) == 0:
        jump_sizes = np.array([0.0])

    lam = np.sum(jump_mask) / (len(ds) * dt)

    return JumpCIRParams(kappa, theta, sigma, lam, jump_sizes, s.iloc[0])


# =========================================================
# SPREAD SIMULATION
# =========================================================

def simulate_spread_paths(params, n_paths, T=10, dt=1/52, seed=42):

    n_steps = int(T / dt)
    paths = np.zeros((n_steps + 1, n_paths))
    paths[0] = params.s0

    rng = np.random.default_rng(seed)

    for t in range(n_steps):

        S = np.maximum(paths[t], 0)

        dW = rng.standard_normal(n_paths) * np.sqrt(dt)
        drift = params.kappa * (params.theta - S) * dt
        diffusion = params.sigma * np.sqrt(S) * dW

        jump_counts = rng.poisson(params.lam * dt, size=n_paths)
        jumps = np.zeros(n_paths)

        idx = np.repeat(np.arange(n_paths), jump_counts)
        if len(idx) > 0:
            sampled = rng.choice(params.jump_sizes, size=len(idx))
            np.add.at(jumps, idx, sampled)

        paths[t+1] = np.maximum(S + drift + diffusion + jumps, 0)

    return paths


# =========================================================
# CPDO SIMULATION
# =========================================================

def run_cpdo_simulation(spread_paths, cpdo_params, sofr_series, dt=1/52):

    n_steps, n_paths = spread_paths.shape[0] - 1, spread_paths.shape[1]

    nav = np.zeros((n_steps + 1, n_paths))
    nav[0] = 100

    default = np.zeros(n_paths, dtype=bool)

    sofr_interp = np.interp(
        np.arange(n_steps),
        np.linspace(0, n_steps, len(sofr_series)),
        sofr_series
    )

    for t in range(n_steps):

        S = spread_paths[t]
        dS = spread_paths[t+1] - S
        NAV = nav[t]

        alive = NAV > cpdo_params.floor_nav

        S_safe = np.maximum(S, 1e-6)
        NAV_safe = np.maximum(NAV, 1e-6)

        # ---- Exposure logic ----
        gap = cpdo_params.target_nav - NAV

        exposure_gap = gap / (cpdo_params.dv01 * S_safe)
        base_exposure = NAV

        exposure = np.where(gap > 0, exposure_gap, base_exposure)

        L = exposure / NAV_safe
        L = np.clip(L, 0, cpdo_params.max_leverage)
        L = np.where(alive, L, 0)

        exposure = L * NAV

        # ---- PnL ----
        carry = exposure * (S / 10000) * dt
        mtm = -exposure * cpdo_params.dv01 * dS
        interest = sofr_interp[t] * NAV * dt
        fees = cpdo_params.management_fee * NAV * dt

        roll_cost = 0
        if t % cpdo_params.roll_every_steps == 0 and t > 0:
            roll_cost = cpdo_params.roll_cost_bps * 1e-4 * NAV

        nav_next = NAV + carry + mtm + interest - fees - roll_cost

        nav[t+1] = np.where(alive, nav_next, cpdo_params.floor_nav)
        nav[t+1] = np.maximum(nav[t+1], cpdo_params.floor_nav)

        default |= nav[t+1] <= cpdo_params.floor_nav

    return nav, default


# =========================================================
# MAIN (WITH VOL TEST)
# =========================================================

if __name__ == "__main__":

    print("Loading data...")

    # CDX
    cdx = pd.read_csv("CDX IG CDSI GEN 5Y Corp(CDX IG CDSI GEN 5Y Corp).csv", sep=";")
    cdx.columns = ["Date", "Spread"]
    cdx["Spread"] = pd.to_numeric(cdx["Spread"], errors="coerce")
    spreads = cdx["Spread"].dropna()

    # SOFR
    sofr = pd.read_csv("SOFR rates(Daily).csv", sep=";")
    sofr["SOFR"] = (
        sofr.iloc[:,1].astype(str).str.replace(",", ".", regex=False).astype(float)
    )
    sofr_series = (sofr["SOFR"] / 100).dropna().values

    cpdo_params = CPDOParams()

    print("\nRunning volatility sensitivity test...\n")

    for vol_multiplier in [1.0, 1.3, 1.5, 2.0, 3.0, 5.0, 10.0]:

        params = calibrate_jump_cir(spreads)

        # ===== VOLATILITY STRESS =====
        params.sigma *= vol_multiplier

        spread_paths = simulate_spread_paths(params, n_paths=5000)
        nav_paths, default = run_cpdo_simulation(
            spread_paths, cpdo_params, sofr_series
        )

        pd_est = np.mean(default)
        mean_nav = np.mean(nav_paths[-1])

        print(f"Vol multiplier: {vol_multiplier}")
        print(f"PD: {pd_est:.4f}")
        print(f"Mean NAV: {mean_nav:.2f}")
        print("-" * 40)