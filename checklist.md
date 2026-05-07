# CPDO Implementation Checklist

Work through each section in order. Each section corresponds to a notebook cell group.
Check off items as completed. Explanations of what was done are included under each section for review.

---

## Section 1 — Data Loading & EDA

- [x] 1.1 Load CDX.NA.IG 5Y data, parse dates, sort ascending, drop NaNs
- [x] 1.2 Load SOFR daily data, parse dates, convert from % to decimal, sort ascending
- [x] 1.3 Validate: check for gaps, duplicate dates, negative spreads
- [x] 1.4 Plot: CDX spread history with annotations (COVID-19 March 2020, missing GFC period)
- [x] 1.5 Plot: SOFR history
- [x] 1.6 Print summary statistics: mean, std, min, max, percentiles for spreads
- [x] 1.7 State explicitly: data covers 2011–2026, GFC (2007–2009) is absent, and what that implies for calibration

**What was done:**
Both CSV files use semicolons as delimiters and European decimal notation (commas instead of periods), requiring `.str.replace(',', '.')` before casting to float. SOFR rates were divided by 100 to convert from percent to decimal.

**Validation findings:** Both datasets are clean — no duplicates, no nulls, no negative spreads. CDX has 3,655 trading days (Sep 2011 – Apr 2026); SOFR has 5,579 days (Jan 2004 – Apr 2026).

**Key data statistics:** CDX spread mean = 69.6 bps, std = 19.0 bps, range = 43.8–151.8 bps. SOFR (overlapping period) mean = 2.1%, range = 0.19–4.95%.

**Critical limitation flagged:** The GFC (2007–2009) is absent from the CDX data. During the crisis, CDX.NA.IG spreads peaked at approximately 280 bps — nearly double our sample's maximum. Any model calibrated to this data will underestimate tail spread risk. This is precisely the same data blindspot that affected Moody's and S&P in 2005–2007, and it is addressed via stress testing in Section 9.

---

## Section 2 — CPDO Product Design

- [x] 2.1 Define and document all CPDO parameters in a single dataclass:
  - Initial NAV = 100
  - Target NAV = 150  (CPDO "cashes out" here)
  - Floor NAV = 10  (CPDO "defaults" here — 90% principal loss)
  - Max leverage = 15x
  - Tenor = 10 years
  - Investor coupon = 3M SOFR + 150 bps, paid quarterly
  - Management fee = 30 bps per annum
  - Roll frequency = every 6 months (steps 126 apart at dt=1/252)
  - Roll cost = 2 bps per roll
  - Recovery rate = 40% (LGD = 60%)
  - N names in index = 125
  - Risky duration (DV01 base) = 4.5 years
- [x] 2.2 Write a clear prose description of the product
- [x] 2.3 Describe all cash flow components with formulas (carry, MTM, interest, coupon, fee, roll, default loss)
- [x] 2.4 Describe the leverage mechanism and feedback loop

**What was done:**
All parameters are stored in a `CPDOParams` dataclass. Two derived constants computed at instantiation: `dv01 = risky_duration x 1e-4 = 0.00045` (sensitivity of $1 notional to a 1bp spread move) and `lgd = 1 - recovery_rate = 60%`. A shared `time_axis` array and `n_steps` integer are also defined here and reused by all subsequent plotting cells.

**Cash flow anatomy (illustrated at NAV=100, S=70bps, SOFR=4%, year 1):**
At these values the leverage formula gives L = 7.94x, exposure = 793.7.
- Carry income: +5.556/yr
- Interest on collateral: +4.000/yr
- Investor coupon: -5.500/yr (SOFR + 150bps on par notional of 100)
- Management fee: -0.300/yr
- Net carry: +3.756/yr (before MTM and defaults)
- MTM per 1bp widening: -0.357 (a one-time event loss)

**Leverage formula:** `L = shortfall / (nav * carry_rate * T_remaining)`, where shortfall = target_nav - nav, carry_rate = S/10000. This sets exposure so that carry income exactly fills the gap to target over the remaining tenor. Capped at max_leverage (15x), floored at 0.

**Why target_nav = 150:** Designed so the CPDO accumulates 50 in carry above principal (approx. 10yr x 5% annual coupon buffer) before cashing out. Coupon payments are deducted from NAV daily as they accrue.

**Investor coupon is on par (100), not current NAV.** When NAV falls below 100, the coupon drain accelerates the decline as a percentage of current NAV — this makes the product more fragile under stress and is consistent with standard CPDO structures.

**The leverage feedback loop:** Spread widening causes MTM losses (NAV falls), which increases the shortfall, which forces higher leverage, which amplifies the next spread move. This is the primary default mechanism — not individual name defaults.

---

## Section 3 — Spread Model: CIR Calibration

- [x] 3.1 State the CIR model: `dS = kappa(theta - S)dt + sigma*sqrt(S) dW`
- [x] 3.2 Implement OLS calibration on daily increments:
  - Regress `dS` on `[1, S_t]` to get `intercept, slope`
  - `kappa = -slope / dt`, `theta = intercept / (kappa * dt)`
  - **Correct sigma**: `sigma = sqrt(mean(residuals^2 / (S_t * dt)))` — NOT `std(dS)/sqrt(dt)`
- [x] 3.3 Print calibrated parameters: kappa, theta, sigma, s0
- [x] 3.4 Sanity check: kappa > 0 (mean-reverting), theta > 0, sigma > 0
- [x] 3.5 Plot: 20 simulated paths + distribution comparison vs historical

**What was done:**
Calibration by OLS on daily spread increments. The discretised CIR model is `dS = intercept + slope*S_t + e`, where `intercept = kappa*theta*dt` and `slope = -kappa*dt`. Inverting gives kappa and theta directly.

**Critical sigma correction:** The CIR diffusion variance is `sigma^2 * S_t * dt` (not constant). The naive estimator `std(dS)/sqrt(dt)` assumes constant variance and gives sigma = 37.3 — nine times too large. The correct CIR estimator gives sigma = 4.06.

**Calibrated parameters:**
- kappa = 2.28 (mean-reversion speed)
- theta = 67.23 bps (long-term mean; close to sample mean of 69.6 bps)
- sigma = 4.06 (CIR-correct volatility coefficient)
- s0 = 54.29 bps (last observed spread)
- Half-life of mean reversion: 0.30 yr = 77 trading days

**Distributional fit check (500 paths x 10yr):** Simulated mean = 66.6, std = 15.7 vs historical mean = 69.6, std = 19.0. The mean is well-captured but variance is lighter than historical — pure CIR misses the fat-tailed spread spikes. This motivates Section 4.

---

## Section 4 — Jump Component: Crisis Calibration

- [x] 4.1 Explain why pure CIR is insufficient (fat tails, sudden spread spikes)
- [x] 4.2 Identify large moves from historical data: |dS| >= 85th pct (both directions — signed)
- [x] 4.3 Fit jump distribution: empirical resample from crisis dS subsample
- [x] 4.4 Compute state-dependent jump probabilities (p_high <= 10%, p_low <= 5%)
- [x] 4.5 Print calibrated crisis parameters
- [x] 4.6 Implement `simulate_spread_paths()` combining CIR + jumps (daily, dt=1/252)
- [x] 4.7 Plot: 20 paths comparison + three-way distribution (historical / CIR / CIR+Jump)

**What was done:**
Large moves defined as |dS| >= 85th percentile of |dS| = 2.5 bps. 548 such events identified (15% of days).

**Key design decision — both directions (signed), not widening-only:** Using only widening moves as jumps introduces a systematic upward drift. Keeping both widening and tightening preserves the correct mean (jump mean = +0.18 bps, nearly zero).

**Calibrated jump parameters:**
- Jump mean = +0.18 bps, std = 5.42 bps (signed, both directions)
- Regime threshold: spread > 82.7 bps (80th pct of historical)
- p_high = 10.0% (capped from raw 33.7%) — jump probability in high-spread regime
- p_low = 5.0% (capped from raw 10.3%) — jump probability in low-spread regime

**Distributional fit with jumps (500 paths):** Simulated mean = 67.9, std = 18.7 vs historical mean = 69.6, std = 19.0. Near-perfect match.

---

## Section 5 — Default Loss Model

- [x] 5.1 CDX mechanics: N=125, each default costs (1/N) x LGD x exposure
- [x] 5.2 Risk-neutral lambda = S / (10000 x LGD x risky_duration) — state-dependent, theoretically grounded
- [x] 5.3 n_defaults ~ Poisson(N x lambda_rn x dt); loss = n_def x (1/N) x exposure x LGD
- [x] 5.4 Loss/carry = 1/risky_duration = 22% by construction — MTM still dominant (1bp widen = 16 days carry)

**What was done:**
Implemented Poisson aggregate default losses. `compute_default_loss` derives LGD internally from `cpdo.recovery_rate` — the function is self-contained and does not rely on any global variables.

**Risk-neutral lambda vs physical lambda:**
Used risk-neutral default intensity `lambda = S / (10000 x LGD x risky_duration)` rather than a fixed physical rate (~0.15%/yr). The risk-neutral rate has clean theoretical grounding: it is the intensity implied by the CDS spread under the no-arbitrage condition spread = lambda x LGD x risky_duration. It is also state-dependent.

**Confirmed MTM dominance:** At L=8x, S=70bps: 1bp spread widening erases 16 days of net carry income. Default losses consume only 22% of carry. Spread dynamics (MTM) dominate.

---

## Section 6 — CPDO Monte Carlo Simulation (Base Case)

- [x] 6.1 Implemented `run_cpdo_simulation()` with all cash flow components
- [x] 6.2 All components applied per step: leverage, carry, MTM, interest, coupon (quarterly on par), fee, roll, default loss, upper/lower triggers
- [x] 6.3 10,000 paths, T=10yr, dt=1/252, runtime ~2s
- [x] 6.4 Returns: final_nav, defaulted, cashed_out, event_year
- [x] 6.5 Optional `record=True` flag records full NAV history per path (replaces old `record_cpdo_paths` function)
- NOTE: Base case PD = 0% — correct, mirrors why calm-data calibration gave AAA ratings.

**What was done:**
`run_cpdo_simulation()` handles both the 10,000-path summary run and the 50-path trajectory run via a single `record=True` flag. Spread paths are pre-generated upfront, then indexed into at each step. SOFR held constant at last observed value (3.91%).

**Coupon is paid on par (initial_nav=100)** as a scalar, not on current NAV. This is consistent with standard CPDO contract terms.

---

## Section 7 — Results & Analysis (Base Case)

- [x] 7.1 PD=0%, Cash-out=37%, Alive=63%, Mean NAV=119, Median=118
- [x] 7.2 50 sample NAV paths color-coded (green=cashed-out, blue=alive, red=defaulted)
- [x] 7.3 Final NAV histogram from 10,000 paths
- [~] 7.4 Skipped — PD=0% in base case, no defaults to plot
- [~] 7.5 Skipped — leverage dynamics clear from Section 2 formula
- [~] 7.6 Skipped — spread paths shown in Section 4

**Base case findings:**
- PD = 0.00% — the floor (NAV=10) is never reached. Min final NAV across all 10,000 paths = ~40.
- 37% of paths cash out (hit NAV=150), typically within 3–5 years.
- The remaining 63% reach maturity with NAVs between ~40 and 150 (mean 119, median 118).
- Max simulated spread across all paths = ~200 bps; the GFC peak of 280 bps is never reached.

---

## Section 8 — Rating Grade Assignment

- [ ] 8.1 Present standard annual PD to rating mapping table (S&P / Moody's scale)
- [ ] 8.2 Convert simulated 10-year PD to implied annual PD: `annual_PD = 1 - (1 - PD_10yr)^(1/10)`
- [ ] 8.3 Assign rating grade and justify based on the mapping
- [ ] 8.4 Comment on what rating this CPDO "should" have received vs what it got (AAA) in 2005

*(Not yet implemented)*

---

## Section 9 — Stress Test: Crisis Scenario

- [x] 9.1 Scenario A (s0=200bps): PD=0%, Cash-out=98% — high spreads -> low leverage (2.5x) -> carry fills gap quickly.
- [x] 9.2 Scenario B (+150bps shock at yr 3): PD=51%, Cash-out=2% — mid-life shock hits already-leveraged CPDO; NAV spiral drives half of paths to floor.
- [x] 9.3 2x2 plot: NAV paths + distributions for both scenarios
- [x] 9.4 Summary table: Base (0%) / Scenario A (0%, 98% CO) / Scenario B (51%)

**Scenario A — Elevated starting spread (s0=200bps):**
Result: PD=0%, Cash-out=98%, Mean NAV=149.
At s0=200bps, leverage = 50/(100 x 0.02 x 10) = 2.5x. Low leverage means small MTM sensitivity and high annual carry. Nearly all paths hit the target within 1–2 years.

**Scenario B — Mid-life spread shock (+150bps at year 3):**
Result: PD=51%, Cash-out=2%, Mean NAV=35.
By year 3, leverage is elevated (L = 10–12x). When spreads jump by 150bps, MTM losses = L x 100 x 4.5e-4 x 150 = 67–81 NAV points in one step — immediately near or through the floor.

**Summary table:**

| Scenario | PD | Cash-out | Mean NAV |
|---|---|---|---|
| Base (s0=54bps) | 0% | 37% | 119 |
| Scenario A (s0=200bps) | 0% | 98% | 149 |
| Scenario B (+150bps yr3) | 51% | 2% | 35 |

---

## Section 10 — Sensitivity Analysis

- [ ] 10.1 Starting spread sweep: run simulation across s0 = 30, 50, 70, 100, 130, 160, 200, 250 bps
  - Plot PD and cash-out rate vs s0 on the same axes
  - Shows the counterintuitive result: low starting spreads -> high leverage -> high PD
- [ ] 10.2 Shock timing x magnitude heatmap:
  - Shock sizes: +50, +100, +150, +200, +250 bps
  - Shock years: 1, 2, 3, 5, 7
  - Each cell = PD from 10,000-path simulation
  - Shows that mid-life shocks are deadliest (leverage has built up but not yet unwound)

*(Not yet implemented)*

---

## Section 11 — Why Rating Agencies Got It Wrong

- [ ] 11.1 Explain how Moody's and S&P rated CPDOs at the time:
  - Used Gaussian copula / CDOROM to model joint default probabilities
  - Assumed low, stable default correlation between IG names
  - Relied on short historical samples (2002–2006) with no major credit stress
  - Assumed mean reversion would prevent prolonged spread widening
- [ ] 11.2 Identify the three core errors:
  - **Correlation underestimation**: IG names became highly correlated in a crisis — the copula assumption broke down
  - **Tail risk ignored**: Gaussian assumptions missed fat tails and spread gap risk
  - **Feedback loop not modelled**: No model captured the leverage spiral (spread widening -> higher leverage -> larger MTM losses -> faster NAV collapse)
- [ ] 11.3 Connect to your own model:
  - Show that even with available (post-crisis) data and a jump model, PD is non-trivial under stress
  - Argue that a model calibrated to 2002–2006 data (no crisis, spreads ~25–50 bps) would produce near-zero PD
  - Use the starting spread sweep (Section 10) to demonstrate how sensitive PD is to starting conditions
- [ ] 11.4 Conclude with the rating implication: models that ignore fat tails and the leverage feedback loop will systematically understate PD

*(Not yet implemented)*

---

## Code Quality Log

**Simplification pass (completed):**
- All code cells rewritten for readability: plain English variable names, no underscore-prefixed temporaries, individual rcParams assignments instead of dict update
- Non-ASCII characters removed from all code (Greek letters, em-dashes, special arrows)
- Print statements made blind to results — no inline interpretation or analysis
- `record_cpdo_paths()` merged into `run_cpdo_simulation()` via `record=True` flag, eliminating ~60 lines of duplicated loop code
- `@dataclass(eq=False)` removed from `JumpParams` (unnecessary)
- OLS output variables renamed from `alpha/beta` to `intercept/slope`

**Logical fixes (completed):**
- `import time` and `from matplotlib.lines import Line2D` moved to top imports cell — cells can now run in any order without NameError
- `compute_default_loss` now derives LGD internally from `cpdo.recovery_rate` — function is self-contained, no global dependency
- `scenarios` variable renamed across 3 cells: `leverage_curves` (Section 2), `stress_scenarios` (Section 9), `summary` (Section 9 table) — no more name collision
- `time_axis` defined once in the params cell (`n_steps + 1` points) and reused by all plotting cells — 3 redundant redefinitions removed
- Hardcoded `range(50)` in path plot loops replaced with `range(nav_hist.shape[1])` — adapts automatically to any n_paths

## Implementation Notes

- All simulations use `dt = 1/252` (daily)
- Random seed fixed for reproducibility (spread simulation: seed+1, CPDO simulation: seed)
- Vectorised numpy operations across paths at every step; the time loop over steps is unavoidable due to path-dependence of NAV
- Runtime: ~2s per 10,000-path simulation; ~7s for all three scenarios combined
- Notebook has 31 cells across Sections 1–7 and 9 (Sections 8, 10, 11 pending)
