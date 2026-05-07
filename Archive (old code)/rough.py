# =========================================================
# CPDO MONTE CARLO — FIXED & REALISTIC VERSION
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
class CPDOParams:
    target_nav: float = 100.0
    floor_nav: float = 10.0

    # FIX 5: realistic leverage
    max_leverage: float = 15.0

    # FIX 6: stronger MTM sensitivity
    dv01: float = 0.0015

    management_fee: float = 0.003

    # FIX 12: higher roll costs
    roll_cost_bps: float = 3.0
    roll_every_steps: int = 26

    recovery_rate: float = 0.4


# =========================================================
# CALIBRATION (UNCHANGED CORE IDEA)
# =========================================================

def calibrate_cir(spread_series, dt=1/52):

    s = pd.Series(spread_series).dropna().reset_index(drop=True)

    s_t = s[:-1].values
    ds = s.diff().dropna().values

    X = np.vstack([np.ones_like(s_t), s_t]).T
    alpha, beta = np.linalg.lstsq(X, ds, rcond=None)[0]

    kappa = max(0.1, -beta / dt)
    theta = max(1, alpha / (kappa * dt))
    sigma = np.std(ds) / np.sqrt(dt)

    return CIRParams(kappa, theta, sigma, s.iloc[0])


# =========================================================
# SPREAD SIMULATION WITH FAT TAILS (FIX 4, 7, 10)
# =========================================================

def simulate_spread_paths(params, n_paths, T=10, dt=1/52, seed=42):

    n_steps = int(T / dt)
    paths = np.zeros((n_steps + 1, n_paths))
    paths[0] = params.s0

    rng = np.random.default_rng(seed)

    for t in range(n_steps):

        S = np.maximum(paths[t], 1e-6)

        dW = rng.standard_normal(n_paths) * np.sqrt(dt)

        # CIR diffusion (NO volatility damping anymore)
        drift = params.kappa * (params.theta - S) * dt
        diffusion = params.sigma * np.sqrt(S) * dW

        # FIX 10: occasional jump shocks (crisis)
        jump = rng.choice([0, 1], size=n_paths, p=[0.97, 0.03])
        jump_size = jump * rng.normal(0.5 * S, 0.2 * S)

        dS = drift + diffusion + jump_size

        paths[t+1] = np.clip(S + dS, 1e-6, 2000)

    return paths


# =========================================================
# CPDO SIMULATION — FULLY FIXED
# =========================================================

def run_cpdo_simulation(spread_paths, cpdo_params, sofr_series, dt=1/52):

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

        # =====================================================
        # FIX 5: AGGRESSIVE LEVERAGE (CPDO STYLE)
        # =====================================================
        L = 1 + 5 * (cpdo_params.target_nav - NAV_safe) / cpdo_params.target_nav
        L = np.clip(L, 0, cpdo_params.max_leverage)

        leverage[t] = L

        exposure = L * NAV

        # =====================================================
        # PnL COMPONENTS
        # =====================================================
        carry = exposure * (S / 10000) * dt
        mtm = -exposure * cpdo_params.dv01 * dS
        interest = sofr_interp[t] * NAV * dt
        fees = cpdo_params.management_fee * NAV * dt

        # =====================================================
        # FIX 1–3: TRUE DEFAULT SIMULATION
        # =====================================================
        S_decimal = S / 10000

        # FIX 2: proper intensity
        lambda_t = S_decimal / LGD

        default_prob = 1 - np.exp(-lambda_t * dt)

        # simulate default event
        uniform = rng.random(n_paths)
        default_event = (uniform < default_prob) & alive

        # FIX 3: full LGD jump loss
        jump_loss = exposure * LGD * default_event

        # =====================================================
        # FIX 12: roll cost
        # =====================================================
        roll_cost = 0
        if t % cpdo_params.roll_every_steps == 0 and t > 0:
            roll_cost = cpdo_params.roll_cost_bps * 1e-4 * exposure

        # =====================================================
        # NAV UPDATE
        # =====================================================
        nav_next = NAV + carry + mtm + interest - fees - roll_cost - jump_loss

        nav[t+1] = nav_next

        # =====================================================
        # FIX 8: TRUE DEFAULT CONDITION
        # =====================================================
        newly_defaulted = (nav_next <= cpdo_params.floor_nav) & alive
        default[newly_defaulted] = True
        default_time[newly_defaulted] = t * dt

        # once defaulted → NAV stays at floor
        nav[t+1][default] = cpdo_params.floor_nav

    return nav, default, leverage, default_time


# =========================================================
# MAIN
# =========================================================

if __name__ == "__main__":

    print("Loading data...")

    cdx = pd.read_csv("CDX IG CDSI GEN 5Y Corp(CDX IG CDSI GEN 5Y Corp).csv", sep=";")
    cdx.columns = ["Date", "Spread"]
    cdx["Spread"] = pd.to_numeric(cdx["Spread"], errors="coerce")
    spreads = cdx["Spread"].dropna()

    sofr = pd.read_csv("SOFR rates(Daily).csv", sep=";")
    sofr["SOFR"] = (
        sofr.iloc[:,1].astype(str).str.replace(",", ".", regex=False).astype(float)
    )
    sofr_series = (sofr["SOFR"] / 100).dropna().values

    cpdo_params = CPDOParams()

    print("\nRunning simulation...\n")

    params = calibrate_cir(spreads)

    spread_paths = simulate_spread_paths(params, n_paths=10000)

    nav, default, leverage, default_time = run_cpdo_simulation(
        spread_paths, cpdo_params, sofr_series
    )

    pd_est = np.mean(default)
    print(f"\n🔥 PD: {pd_est:.4f}")

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