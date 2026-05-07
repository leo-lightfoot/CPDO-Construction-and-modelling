# CPDO Analysis Report
## Constant Proportion Debt Obligation — Design, Simulation, and Default Probability Estimation

---

## Overview

This report documents the full construction and analysis of a Constant Proportion Debt Obligation (CPDO) using CDX.NA.IG 5Y spread data. A CPDO is a structured credit product that sells protection on a credit index (CDX) with dynamic leverage, using the carry income to pay investors a coupon above the risk-free rate. The leverage is adjusted daily so that expected carry income from the remaining tenor exactly fills the gap between current NAV and target NAV.

The central question — and the historical lesson — is why CPDOs were rated AAA in 2005–2007 when the underlying risk was far more severe. This analysis replicates the modelling process, shows why calm-data calibration produces AAA ratings, and then demonstrates what happens under realistic crisis conditions.

---

## Section 1 — Data

### What was done
Two datasets were loaded: CDX.NA.IG 5Y credit spreads and SOFR daily rates. Both required European decimal formatting (commas replaced with periods) before parsing. SOFR was divided by 100 to convert from percent to decimal.

### Key numbers

| Dataset | Rows | Date range | Range |
|---------|------|------------|-------|
| CDX.NA.IG 5Y | 3,655 trading days | Sep 2011 – Apr 2026 | 43.8 – 151.8 bps |
| SOFR | 5,579 days | Jan 2004 – Apr 2026 | 0.19% – 5.23% |

CDX summary statistics (2011–2026):
- Mean = 69.6 bps, Std = 19.0 bps, Median = 65.1 bps
- 5th pct = 48.9 bps, 95th pct = 108.1 bps

### Image: `01_cdx_spread.png`
The CDX spread chart shows three distinct stress periods: the EU Debt Crisis (Oct 2011, peak ~150 bps), the Oil/China stress (Feb 2016, peak ~115 bps), and COVID-19 (Mar 2020, spike to ~150 bps). Between stress events, spreads revert toward 50–70 bps. The annotation in the top-left marks the critical limitation: data starts September 2011. The GFC peak of ~280 bps in 2008–2009 is entirely absent from this dataset.

### Image: `02_sofr_rate.png`
SOFR shows two extended near-zero periods (2009–2015 post-GFC, 2020–2022 post-COVID) and a sharp tightening cycle from 2022 to 2023 (approaching 5%). The simulation uses the mean SOFR over the CDX sample period (2.119%), visible as approximately the midpoint of the historical range.

### Critical data limitation
The absence of the GFC (2007–2009) from the CDX data is the core modelling blindspot. Rating agencies in 2005 faced a similar or worse situation — their data went back to 2002, when IG spreads were around 25–50 bps and the credit market had never experienced a systemic crisis. A model calibrated to this data cannot produce meaningful estimates of crisis-era PD. This is addressed directly in the stress tests (Section 9) and sensitivity analysis (Section 10).

---

## Section 2 — CPDO Product Design

### What was done
A `CPDOParams` dataclass defines all product parameters. Two derived constants are computed: DV01 (price sensitivity per basis point per dollar of notional) and LGD (loss given default).

### Parameters

| Parameter | Value | Meaning |
|-----------|-------|---------|
| Initial NAV | 100 | Starting value |
| Target NAV | 150 | Cash-out trigger — CPDO winds up |
| Floor NAV | 10 | Default trigger — 90% principal loss |
| Max leverage | 15× | Cap on position size |
| Tenor | 10 years | Product life |
| Investor coupon | SOFR + 150 bps | Paid quarterly on par (100) |
| Management fee | 30 bps p.a. | Operating cost |
| Roll cost | 2 bps per roll | Cost of rolling the CDX position every 6 months |
| N names | 125 | CDX.NA.IG index composition |
| Risky duration | 4.5 years | DV01 base |
| Recovery rate | 40% | LGD = 60% |
| DV01 | 0.00045 | NAV loss per 1 bp spread widening per $1 exposure |

### Cash flow mechanics (NAV=100, spread=70 bps, SOFR=4%, year 1)

At these values, leverage = 7.94×, exposure = 793.7.

| Component | Daily | Annual |
|-----------|-------|--------|
| (+) Carry income | +0.0220 | +5.556 |
| (+) Interest on collateral | +0.0159 | +4.000 |
| (-) Investor coupon | -0.0218 | -5.500 |
| (-) Management fee | -0.0012 | -0.300 |
| Net carry | +0.0149 | +3.756 |
| (-) MTM per 1 bp widening | -0.3571 | (event) |

The net carry of 3.756 p.a. is the income buffer. A single 1 bp spread widening wipes 0.357 in NAV — equivalent to 24 days of net carry in one move.

### Leverage formula

`L = shortfall / (NAV × carry_rate × T_remaining)`

where shortfall = target_nav − nav and carry_rate = spread / 10,000. This sets exposure so that carry income, if earned at the current spread for the rest of the tenor, exactly fills the shortfall to target. The formula is capped at 15× and floored at 0.

### Image: `03_leverage_vs_nav.png`
Three curves show leverage vs NAV at years 1, 5, and 9 of the product's life (at spread = 70 bps). At year 1 (blue curve), the leverage stays below 15× until NAV falls below ~75. At year 9 (red curve), the leverage hits the cap at NAV = ~140 — meaning even a small shortfall late in life triggers maximum leverage. This is because T_remaining is small, so the denominator collapses and the formula demands very high exposure to fill the gap in time. The dotted lines show the initial NAV (100) and the 15× cap.

### The leverage feedback loop
Spread widening hits NAV twice simultaneously: the MTM loss reduces NAV (larger shortfall), which forces the leverage formula to demand higher exposure, which then amplifies the next spread move. This spiral — *widen → lose → lever up → lose more* — is the primary default mechanism. Individual name defaults are secondary.

---

## Section 3 — CIR Spread Model

### What was done
The Cox-Ingersoll-Ross (CIR) model is calibrated to daily CDX spread increments via OLS regression. The model is:

`dS = kappa × (theta − S) × dt + sigma × sqrt(S) × dW`

Mean reversion (kappa) and long-run mean (theta) are recovered from the OLS intercept and slope. The volatility coefficient (sigma) uses the CIR-correct estimator: since CIR variance is `sigma² × S × dt` (not constant), the naive `std(dS)/sqrt(dt)` overstates sigma by a factor of ~9.

### Calibrated parameters

| Parameter | Value | Meaning |
|-----------|-------|---------|
| kappa | 2.2759 | Mean-reversion speed |
| theta | 67.23 bps | Long-run average spread |
| sigma | 4.0620 | Volatility coefficient (CIR-correct) |
| s0 | 54.29 bps | Current spread (last observation) |
| Half-life | 0.30 yr (77 days) | Time for half of any shock to revert |

The naive sigma estimator gives 37.3 — nine times larger. Using that value would produce wildly unrealistic paths with spreads regularly spiking to 500+ bps.

### Image: `04_cir_paths.png`
**Left panel:** 20 simulated CIR paths over 10 years. Paths oscillate around the theta line (red dashed, 67.2 bps) with the grey band showing the historical range (44–152 bps). Paths occasionally spike above the historical maximum but generally stay within range. The mean reversion is visible — paths that wander high are pulled back toward theta within months.

**Right panel:** Distribution comparison. The simulated distribution (orange) matches the historical (blue) well in the centre but has lighter tails. The historical distribution has a fatter right tail (spread spikes) that the pure CIR model fails to capture. Simulated std = 15.6 vs historical std = 19.0 — an 18% gap. This motivates the jump component.

---

## Section 4 — Jump Component

### What was done
Large daily spread moves (|dS| ≥ 85th percentile = 2.5 bps) are identified in both directions (widening and tightening). Jump probability is state-dependent: higher when spreads are elevated (above the 80th percentile = 82.7 bps), lower otherwise. At each simulation step, a jump fires with probability p_j and the jump size is drawn from the empirical distribution of historical large moves.

### Why both directions matter
Using only widening moves as jumps introduces a persistent upward drift — simulated mean rises to ~111 bps vs historical 70 bps. Including tightening jumps too preserves the correct mean (jump mean = +0.18 bps, approximately zero).

### Calibrated jump parameters

| Parameter | Value |
|-----------|-------|
| Large move threshold | 2.51 bps (85th pct of |dS|) |
| Large move events | 548 (15.0% of days) |
| Jump mean | +0.18 bps (nearly zero) |
| Jump std | 5.42 bps |
| Jump range | −31.4 to +27.8 bps |
| Regime threshold | 82.71 bps (80th pct of historical spread) |
| p_high (spread > 82.7 bps) | 10.0% |
| p_low (spread ≤ 82.7 bps) | 5.0% |

### Image: `05_cir_jump_paths.png`
**Left panel:** CIR + Jump paths (orange) vs pure CIR paths (blue) over 10 years. The orange paths show sharper, more sudden moves — visible spikes that the smooth CIR paths do not produce. Both sets revert to the theta line over time, but the jump model explores a wider range in shorter periods.

**Right panel:** Three-way distribution comparison. The jump model (orange) closely matches the historical distribution (blue), recovering the fat right tail that pure CIR (green) misses. Simulated stats: CIR mean=66.8 / std=15.6; CIR+Jump mean=67.7 / std=18.7; Historical mean=69.6 / std=19.0. The jump component adds ~3 units of standard deviation and restores the tail shape.

---

## Section 5 — Default Loss Model

### What was done
Default losses use a risk-neutral Poisson intensity: `lambda = S / (10,000 × LGD × risky_duration)`. This is the no-arbitrage condition — it is the default intensity implied by the observed CDS spread. Each default costs `(1/N) × exposure × LGD`.

### Key numbers (at L=8×, NAV=100, spread=70 bps)

| Quantity | Value |
|----------|-------|
| lambda_rn per name per year | 0.259% |
| Per-name default loss | 3.81 (0.480% of exposure) |
| Expected annual default loss | 1.23 |
| Annual carry income | 5.56 |
| Default loss / carry | 22.2% |
| MTM per 1 bp widening | 0.357 |

The 22.2% ratio is not a coincidence — it equals `1 / risky_duration = 1/4.5` by construction of the risk-neutral intensity. The CPDO's profit comes from the spread risk premium: physical default rates are lower than risk-neutral rates, so actual losses are less than 22% of carry.

MTM dominates: a single 1 bp spread widening (0.357 NAV) is equivalent to 16.2 days of carry income. Default losses, bounded by the Poisson process and index granularity, are a secondary risk channel.

---

## Section 6 — Monte Carlo Simulation

### What was done
`run_cpdo_simulation()` runs 10,000 paths over 10 years (2,520 daily steps). At each step:
1. Look up pre-generated spread `S[t]` and compute `dS = S[t+1] − S[t]`
2. Compute leverage from the shortfall formula (capped at 15×)
3. Apply carry, interest, MTM, default loss, fee, and roll costs
4. Accrue and pay quarterly investor coupon (on par value of 100)
5. Check floor (NAV ≤ 10) and target (NAV ≥ 150) triggers

SOFR is held constant at 2.119% (the historical mean over the CDX sample period, Sep 2011–Apr 2026). This is more representative than the last observed value for a 10-year forward simulation. When NAV is at par (100), SOFR and interest income cancel exactly. When NAV falls below par — as in distressed scenarios — the coupon (paid on par) exceeds interest income (earned on current NAV), creating a net drain of `sofr_rate × (100 − nav)` per year. A lower SOFR rate therefore reduces this excess drain in stressed paths.

Spread paths are pre-generated upfront and indexed into at each step. The optional `record=True` flag stores full NAV histories for trajectory plotting.

---

## Section 7 — Base Case Results

### Key numbers

| Outcome | Rate | Threshold |
|---------|------|-----------|
| Defaulted | 0.00% | NAV ≤ 10 |
| Cashed out | 34.99% | NAV ≥ 150 |
| Alive at maturity | 65.01% | — |
| Mean final NAV | 119.25 | — |
| Median final NAV | 116.90 | — |
| Minimum final NAV | 41.84 | — |

### Image: `06_nav_base_case.png`
**Left panel:** 50 sample NAV paths coloured by outcome: green (cashed out, NAV hits 150), blue (alive at maturity), red (defaulted — none visible). Green paths typically hit the target within 2–5 years and are frozen there. Blue paths meander between 60 and 149 for the full 10 years. No red paths exist in the base case — the floor (10) is never reached across all 10,000 simulations.

**Right panel:** Final NAV distribution from 10,000 paths. The green spike at NAV=150 (the cash-out boundary) represents the 37% of paths that hit target. The blue distribution (alive at T) spans roughly 40–149, with the bulk between 100 and 140. No paths reach the floor at NAV=10.

### What this means
The base case model, calibrated to 2011–2026 data, produces zero default probability. This is exactly what the rating agencies observed with their 2002–2006 calibrations — benign data produces benign forecasts. The model cannot see what it has not been trained on. The maximum simulated spread across all 10,000 paths is approximately 200 bps; the GFC peak of 280 bps is never reached.

---

## Section 9 — Stress Tests

Two scenarios test CPDO behaviour outside the calibration sample.

### Scenario A — Elevated starting spread (s0 = 200 bps)

The CIR model is started at 200 bps (GFC-era level) with all other parameters unchanged.

**Result: PD = 0.00%, Cash-out = 96.25%, Mean NAV = 148.71**

At s0 = 200 bps, the leverage formula gives `L = 50 / (100 × 0.02 × 10) = 2.5×`. Because carry_rate (S/10,000) is high, only modest leverage is needed to fill the shortfall. With 2.5× exposure, MTM sensitivity per bp is `2.5 × 100 × 4.5e-4 = 0.11` — small. Annual carry at 2.5× is `2.5 × 100 × 0.02 = 5.0` — large. Nearly all paths accumulate enough carry to hit target within 1–2 years before spreads have a chance to widen enough to cause damage.

**Key insight:** A CPDO issued into a high-spread environment is paradoxically safer than one issued in a calm market. High spreads → low leverage needed → lower MTM risk. The GFC was dangerous for CPDOs *already in existence* (issued at low spreads in 2005–2006), not for hypothetical CPDOs issued at crisis peaks.

### Scenario B — Mid-life spread shock (+150 bps at year 3)

The pre-generated spread paths have +150 bps added permanently from step 756 (year 3 onwards). CIR mean-reversion continues within the paths, but the entire level is shifted up.

**Result: PD = 39.33%, Cash-out = 3.28%, Mean NAV = 45.15**

By year 3, many paths have NAV still near 100 (coupon drain and modest carry have made limited progress toward 150). At that point, leverage from the formula is approximately `L = 50 / (100 × carry_rate × 7) ≈ 10–12×`. When the +150 bps shock hits:
- MTM loss = `L × 100 × 4.5e-4 × 150 ≈ 67–81 NAV points in one step`
- This immediately puts most paths near or below the floor of 10
- For paths that survive the initial shock, the elevated spreads and higher jump probability (p_high = 10%) drive continued deterioration

**Key insight:** This is the GFC story. CPDOs issued in 2005 at ~30–50 bps spreads were running at near-maximum leverage (15×) when IG spreads widened from ~30 to ~280 bps in 2007–2008. A CPDO at 15× leverage with DV01 = 4.5e-4 loses `15 × 100 × 4.5e-4 × 250 = 168.75 NAV points` on a 250 bp widening — more than the entire NAV twice over.

### Image: `07_stress_scenarios.png`
**Scenario A (top row):** Left panel shows nearly all paths immediately rising toward NAV=150 (green), reaching the target within 1–3 years. The distribution (right) has a massive green spike at 150, confirming 98% cash-out. No paths approach the floor.

**Scenario B (bottom row):** Left panel shows the characteristic pattern — paths running normally until year 3, then a sudden vertical drop in NAV across all paths simultaneously. The red cluster at the floor (10) is visible for ~51% of paths. A small green cluster shows paths that cashed out before year 3. The distribution (right) shows a large red spike at NAV=10 (defaulted) and a small green spike at 150, with virtually nothing in between.

### Summary table

| Scenario | PD | Cash-out | Mean NAV | Why |
|---|---|---|---|---|
| Base (s0 = 54 bps) | 0.00% | 34.99% | 119.25 | Calm data — spreads stay within historical range |
| Scenario A (s0 = 200 bps) | 0.00% | 96.25% | 148.71 | High spreads → 2.5× leverage → safe |
| Scenario B (+150 bps yr 3) | 39.33% | 3.28% | 45.15 | Mid-life shock hits 10–12× leveraged position |

---

## Section 8 — Rating Grade Assignment

### Rating scale (S&P / Moody's, approximate 1-year historical average PDs)

| S&P | Annual PD (%) | Moody's |
|-----|--------------|---------|
| AAA | 0.00 | Aaa |
| AA | 0.02 | Aa |
| A | 0.07 | A |
| BBB | 0.24 | Baa |
| BB | 0.97 | Ba |
| B | 4.44 | B |
| CCC/C | 26.06 | Caa/C |

### Implied rating assignment

The 10-year PD is converted to an equivalent annual PD:
`annual_PD = 1 − (1 − PD_10yr)^(1/10)`

| Scenario | 10yr PD | Annual PD | Implied Rating | Actual (2005) |
|----------|---------|-----------|----------------|---------------|
| Base case (s0 = 54 bps) | 0.00% | 0.0000% | AAA | AAA |
| Scenario A (s0 = 200 bps) | 0.00% | 0.0000% | AAA | AAA |
| Scenario B (+150 bps at yr 3) | 39.33% | 4.8744% | B | AAA |

### What this means
The base case model assigns **AAA** — exactly what rating agencies awarded in 2005. This is not because the CPDO is genuinely safe, but because the model is calibrated to data that contains no crisis. Under calm conditions, the model cannot produce PD above zero, so it assigns the highest possible rating.

Under realistic crisis dynamics (Scenario B), the implied annual PD is **4.87%**, placing the product firmly in **B** territory — six notches below AAA. The gap between AAA (actual) and B (stress-implied) represents the full cost of the rating agency modelling failure. A B-rated product was sold to investors as AAA.

---

## Section 10 — Sensitivity Analysis

### 10.1 — Starting spread sweep

**Setup:** s0 varied from 30 to 250 bps; 5,000 paths per point; base case calibration.

**Image: `08_spread_sweep.png`**
The chart has two y-axes: PD (red, left) and cash-out rate (green, right), plotted against starting spread. The PD line is flat at 0% across the entire range — confirming that under calm-data calibration, no starting spread produces default risk. The cash-out curve rises steeply from 0.4% at 30 bps to ~29% at 50 bps, then more gradually to ~99% at 250 bps. The dotted vertical line marks the current s0 = 54 bps, where cash-out is approximately 37%.

**What it means:** The flat PD line is the key result. Under benign market assumptions, the CPDO cannot default regardless of where it starts — the model is structurally incapable of generating risk. The rising cash-out curve reflects the low-leverage dynamic: higher starting spreads require less leverage to fill the shortfall, so carry accumulates faster and the target is hit sooner. This chart explains why agencies got AAA regardless of the spread environment they modelled.

---

### 10.2 — Shock timing × magnitude heatmap

**Setup:** 5×5 grid. Shock magnitudes: +50, +100, +150, +200, +250 bps. Shock timings: years 1, 2, 3, 5, 7. 5,000 paths per cell.

**Image: `09_shock_heatmap.png`**
Green cells (low PD) are concentrated in the left two columns (+50 and +100 bps shocks), where even large-timing shocks produce minimal PD. The transition to yellow/orange occurs at +150 bps, with PD rising from 10.4% (year 1) to 76.3% (year 5) and 75.8% (year 7). The right two columns (+200 and +250 bps) are almost entirely red (PD 65–100%).

**Year 1 row:** PD is lower for moderate shocks (+100 bps: 0.4%, +150 bps: 10.4%) because leverage is still relatively low early in the product's life — the shortfall is large but T_remaining is long, keeping L moderate.

**Year 3–5 rows:** PD peaks here. By year 3–5, three years of coupon drain have reduced NAV without much progress toward target (carry is modest at 54 bps starting spread). The leverage formula at this point gives L ≈ 10–12×, making the position highly exposed to any shock.

**Year 7 row:** PD drops slightly at lower shock magnitudes (+150: 75.8%) compared to year 5 (76.3%) because by year 7, some paths have already cashed out or are closer to target, reducing the average leverage. However, this effect is small — the damage from a large late-life shock is still severe.

**The GFC column (+150 bps, year 3):** 52.4% PD. This cell represents the actual GFC scenario for CPDOs issued in 2005: three years of operation (reducing NAV via coupons but not accumulating much carry at 30–50 bps spreads), then a massive spread widening from 2007–2008.

---

### 10.3 — Max leverage cap sweep

**Setup:** max_leverage varied from 5× to 20×. Two simulations per point: base case (for cash-out) and Scenario B (for PD). 5,000 paths each.

**Image: `10_leverage_cap_sweep.png`**
PD (red) is 0% for caps of 5× and 8×, jumps to ~0.9% at 10×, spikes to ~58% at 12×, then sits around 47–52% at 15–20×. The green cash-out curve rises monotonically with the cap: ~0% at 5×, ~37% at 15×, ~68% at 20×.

**What it means:** There is a clear threshold at approximately 10× leverage. Below this cap, the position's exposure under a +150 bps shock is limited enough that most paths survive: `10 × 100 × 4.5e-4 × 150 = 67.5 NAV points` — still catastrophic for many paths, but leverage lower than the uncapped position. Above 10×, the shock magnitude relative to NAV ensures widespread default.

The monotonically rising cash-out rate shows the other side: restricting leverage to 5× means the CPDO earns carry so slowly it almost never reaches target (~0% cash-out). The leverage cap is a direct trade-off between crisis safety and calm-market performance.

**Regulatory implication:** Setting a leverage cap at 8–10× rather than 15× would reduce Scenario B PD from ~51% to near 0%, with significant cost to calm-market cash-out rates (~0–2% vs 37%). This is a concrete design change that would have materially altered CPDO risk profiles.

---

### 10.4 — Investor spread sweep

**Setup:** Investor coupon spread varied from 25 to 200 bps over SOFR. Two simulations per point: base case (cash-out) and Scenario B (PD). 5,000 paths each.

**Image: `11_investor_spread_sweep.png`**
Clean X-pattern: the two curves cross near 125 bps. PD (red) rises monotonically from 22% at 25 bps to 67% at 200 bps. Cash-out (green) falls monotonically from 72% at 25 bps to 24% at 200 bps. The dotted vertical line marks the current coupon at 150 bps.

**What it means:** The investor coupon is paid on par (100) regardless of current NAV. Each additional basis point of coupon costs `1 bps × 100 / 252 = 0.00040 NAV per day`, compounding over 10 years. Higher coupon spreads drain NAV faster, leaving the CPDO with less buffer when a shock arrives.

At 25 bps (very cheap product), the CPDO has low coupon drain, so more NAV survives into a shock — but even here, Scenario B still produces 22% PD, confirming that the leverage feedback mechanism is the dominant risk channel, not the coupon level.

At 200 bps, the 50 bps additional coupon drain (vs 150 bps base) costs approximately `0.50% × 100 × 10 = 50 NAV over the tenor` in simple terms — essentially consuming the entire target surplus. Paths arrive at the year-3 shock with much lower NAV, giving less distance to the floor, explaining the jump in PD.

The trade-off is stark: designing a CPDO with a lower investor spread would meaningfully reduce crisis PD, but at a direct cost to the investor's yield — the entire product's commercial rationale is the attractive spread over risk-free.

---

## Summary of Key Results

| Metric | Value | Context |
|--------|-------|---------|
| Base case PD | 0.00% | Calm data; spreads never extreme |
| Stress PD (Scenario B) | 39.33% | GFC-style mid-life shock |
| Implied rating (base) | AAA | Matches actual 2005 rating |
| Implied rating (stress) | B | Six notches below actual |
| PD threshold (leverage cap) | ~10× | Below = safe; above = catastrophic |
| PD/Cash-out crossover (coupon) | ~125 bps | Below = cash-out dominant; above = PD dominant |
| Shock threshold | +100 bps | Marginal; +150 bps = catastrophic (>52% PD) |
| Safest CPDO design | High s0, low leverage cap, low coupon | None of these maximise investor yield |

---

## Core Finding

The CPDO is structurally sound under calm conditions — the leverage formula is mathematically consistent and the carry arithmetic works. The product fails for the same reason the ratings failed: the model cannot extrapolate beyond its calibration data.

Three specific failures compounded:

1. **Data blindspot:** No GFC data in the calibration sample. CDX.NA.IG peaked at 280 bps in 2008–2009; the entire 2011–2026 calibration sample never exceeds 152 bps. A model that has never seen 280 bps cannot produce meaningful PD estimates when spreads reach 280 bps.

2. **The leverage spiral was unmodelled:** Rating agency models (Gaussian copula, CDOROM) modelled joint default probabilities but not the dynamic leverage adjustment. The feedback loop — widening → NAV falls → leverage rises → larger next loss — was invisible to static credit models. This report's simulation demonstrates the spiral explicitly.

3. **Calm-data calibration → zero PD:** Any model calibrated only to 2002–2006 data (spreads 25–50 bps, no stress events of note) will assign AAA to a CPDO. The starting spread sweep (Section 10.1) shows this directly: across all starting conditions from 30 to 250 bps, the base case model produces 0% PD. The model is structurally incapable of generating risk from calm inputs.

The stress test results (Section 9) and sensitivity analysis (Section 10) show that under realistic crisis dynamics, the same product carries annual PD of ~7% — firmly in B territory. A six-notch rating error, driven entirely by the choice of calibration data and the omission of the leverage feedback mechanism.
