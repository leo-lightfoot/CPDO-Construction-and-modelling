# CPDO Monte Carlo Model Documentation

## 1. Overview

This document explains the structure, modelling choices, and implementation of a simplified Constant Proportion Debt Obligation (CPDO) simulation model. The objective of the model is to estimate the **probability of default (PD)** of a CPDO using simulated CDS spread dynamics.

The model captures the key economic mechanisms of a CPDO:
- Leveraged exposure to credit indices (CDX)
- Income from CDS premiums (carry)
- Losses from spread movements (mark-to-market)
- Credit losses via defaults
- Dynamic leverage adjustment based on NAV

---

## 2. Model Structure

### 2.1 High-Level Flow

1. Simulate CDS spread paths using a CIR-type process
2. Use spreads to generate:
   - Carry income
   - Mark-to-market P&L
   - Default probabilities
3. Update NAV over time
4. Adjust leverage dynamically
5. Trigger default if NAV hits floor

---

## 3. Spread Model

### 3.1 Model Used

A **mean-reverting CIR-style process** is used:

- Mean reversion toward long-term spread level
- Volatility proportional to square root of spread

Dynamics:

- Drift: pulls spreads toward long-run mean
- Diffusion: introduces randomness proportional to spread level

### 3.2 Parameters

| Parameter | Description |
|----------|------------|
| kappa | Speed of mean reversion |
| theta | Long-term mean spread |
| sigma | Volatility of spreads |
| s0 | Initial spread |

### 3.3 Calibration

Parameters are estimated from historical CDX spread data using:
- Linear regression on spread changes
- Residual-based volatility estimation

---

## 4. CPDO Structure

### 4.1 Key Variables

| Parameter | Description |
|----------|------------|
| target_nav | Target NAV (usually 100) |
| floor_nav | Default threshold (e.g. 10) |
| max_leverage | Maximum allowed leverage |
| dv01 | Sensitivity to spread changes |
| management_fee | Annual fee charged |
| roll_cost_bps | Cost of rolling CDS index |
| roll_every_steps | Frequency of roll (in time steps) |
| recovery_rate | Recovery assumption (typically 40%) |

---

## 5. Cash Flow Components

At each time step, NAV evolves based on:

### 5.1 Inflows

#### (a) CDS Premium (Carry)
- Earned for selling protection
- Proportional to spread and exposure

#### (b) Interest Income
- Earned on collateral (SOFR rate)

---

### 5.2 Outflows

#### (a) Mark-to-Market (MTM)
- Losses when spreads widen
- Gains when spreads tighten

#### (b) Default Losses
- Based on hazard rate derived from spreads

#### (c) Fees
- Management fee applied to NAV

#### (d) Roll Costs
- Cost incurred when CDS index is rolled

---

## 6. Default Modelling

### 6.1 Hazard Rate Approximation

Default intensity is approximated as:

lambda = c × Spread / (1 - Recovery)

where:
- Spread is in basis points
- c is a scaling factor

### 6.2 Default Probability

A linear approximation is used:

p ≈ lambda × dt

### 6.3 Loss Calculation

Expected loss is computed as:

Loss = Exposure × LGD × Default Probability

where:
- LGD = (1 - recovery rate)
- Adjusted to reflect diversification

---

## 7. Leverage Mechanism

Leverage is dynamically adjusted based on NAV:

L = 1 + alpha × (Target NAV - NAV) / Target NAV

Key idea:
- If NAV falls → leverage increases
- If NAV rises → leverage decreases

This creates a **feedback loop**, central to CPDO risk.

---

## 8. NAV Evolution

NAV is updated as:

NAV(t+1) = NAV(t)
           + Carry
           + Interest
           - MTM
           - Default Loss
           - Fees
           - Roll Cost

---

## 9. Default Definition

The CPDO defaults if:

NAV ≤ floor_nav

Once default occurs:
- NAV is floored
- Path is marked as defaulted

---

## 10. Simulation

- Monte Carlo simulation with multiple paths (e.g. 10,000)
- Time horizon: typically 10 years
- Time step: weekly

Outputs:
- Probability of Default (PD)
- Distribution of NAV

---

## 11. Key Modelling Decisions

### ✔ Use of CDX Index
- Instead of modelling individual CDS names
- Simplifies modelling
- Captures systemic credit risk

### ✔ Fractional Default Approximation
- Uses expected loss instead of discrete defaults
- Computationally efficient

### ✔ Linear Hazard Approximation
- Avoids instability from exponential models

### ✔ Controlled Leverage Function
- Prevents unrealistic explosive behaviour

### ✔ Simplified Roll Cost
- Fixed cost instead of full rebalancing model

---

## 12. Limitations

### 12.1 No Individual Name Modelling
- Ignores correlation structure between firms

### 12.2 Simplified Default Process
- Uses continuous approximation instead of discrete events

### 12.3 No Liquidity/Funding Risk
- Does not model margin calls or funding stress

### 12.4 Simplified Spread Dynamics
- No regime switching or crisis dynamics

### 12.5 Simplified Roll Mechanics
- Does not capture index composition changes explicitly

---

## 13. Key Insight

The model demonstrates that:

- CPDO risk is driven by a **feedback loop**:
  - Spread widening → losses → NAV decline → leverage increase → further losses

This mechanism explains why CPDOs were highly sensitive to market conditions and why their risk was underestimated.

---

## 14. Conclusion

This model provides a simplified but realistic framework for analysing CPDO risk. While it abstracts from several real-world complexities, it captures the core dynamics necessary to study default probability and leverage-driven instability.

