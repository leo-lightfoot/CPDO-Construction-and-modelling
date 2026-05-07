# CPDO-Construction-and-modelling - GARCH for validation

We’ve made good progress on building the CPDO model and now have a working end-to-end framework. We decided to take a top-down approach using the CDX.NA.IG 5Y index, rather than modeling individual CDS names. The idea is that the index spread already reflects the aggregate credit risk of its constituents, so it lets us focus on systemic risk. The limitation is that we don’t capture firm-specific defaults, but we address that by modeling spread volatility and jump risk, which proxy for market-wide stress events.

Because of this top-down approach, we’re not modeling the interactions or behavior of individual constituents. That complexity is effectively embedded in the index spread itself, so modeling each name separately would add a lot of effort without materially improving the results for our objective.

For changes in index composition over time, we’re not tracking individual names entering or leaving the index. Instead, we handle this through a simplified roll mechanism, where we apply a roll cost of ~1–2 bps every 6 months (26 weekly steps). This captures the economic impact of rebalancing in a practical way.

On the modeling side, we’re using a Jump-CIR process for spreads, which captures mean reversion, volatility that increases when spreads are higher, and sudden jumps during stress periods. The parameters are calibrated directly from historical CDX data.

We then simulate spread paths using Monte Carlo over a 10-year horizon with weekly time steps (dt = 1/52, ~520 steps) and generate multiple scenarios (e.g., 5,000 paths). These spread paths feed into the CPDO engine.

The CPDO starts with an initial NAV of 100, and we define default as a cash-out event when NAV falls to 10, i.e., 10% of the initial value. So default is not tied to a specific spread level directly, but rather occurs when spread widening leads to losses that reduce NAV below this threshold.

The portfolio uses a dynamic leverage rule, where exposure increases when NAV falls below the target (100), with a maximum leverage cap of 15×. This reflects the typical CPDO behavior of increasing risk to try to recover losses.

In terms of PnL, NAV evolves through:

Carry: income from selling protection, proportional to spread (S/10000)
Mark-to-market (MTM): losses when spreads widen, scaled using DV01 ≈ 0.0005 (based on a 5-year CDS duration)
Interest income: based on SOFR rates (converted from % to decimal)
Fees: ~25 bps annually
Roll costs: ~1–2 bps every 6 months

For validation, we’ve observed that calibration on historical data alone can produce very low default probabilities, because most of the data reflects stable periods. To address this, we’ve been doing sensitivity analysis by increasing volatility (e.g., 1.3×, 1.5×, 2× multipliers) and observing how the probability of default (PD) changes. This helps us understand how the model behaves under stressed conditions. We’ve also discussed using GARCH as a benchmark to check whether our volatility dynamics are realistic, even though it’s not part of the core model.

Overall, the model is now functioning properly, and we’re focusing on ensuring that the assumptions are well-justified and that the results reflect realistic credit risk dynamics.

default intensirty based in exponential distribution
simulate based on distribution whose parameters depend on the spread



                 ┌──────────────────────┐
                 │      INVESTORS       │
                 │   Initial Capital    │
                 │       (NAV=100)      │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │     CPDO VEHICLE     │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │   LEVERAGE ENGINE    │
                 │  Exposure = L × NAV  │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │    CDS PORTFOLIO     │
                 │  (Sell Protection)   │
                 └──────────┬───────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼

 ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
 │   + CARRY    │   │   - MTM      │   │ - DEFAULT    │
 │ CDS Premium  │   │ Spread Move  │   │   LOSSES     │
 └──────┬───────┘   └──────┬───────┘   └──────┬───────┘
        │                  │                  │
        └──────────┬───────┴───────┬──────────┘
                   ▼               ▼

            ┌────────────────────────────┐
            │        NAV UPDATE          │
            │ NAV(t+1) = All Cash Flows  │ 
            └──────────┬─────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼                             ▼

┌──────────────────────┐     ┌──────────────────────┐
│ + INTEREST (SOFR)    │     │ - FEES & ROLL COST   │
└──────────┬───────────┘     └──────────┬───────────┘
           │                              │
           └──────────────┬───────────────┘
                          ▼

              ┌──────────────────────┐
              │ LEVERAGE ADJUSTMENT  │
              │   (Based on NAV)     │
              └──────────┬───────────┘
                         │
                         ▼
                  (Back to Exposure)

------------------------------------------------------

                ⚠ DEFAULT CONDITION ⚠

              ┌──────────────────────┐
              │   NAV ≤ FLOOR (10)   │
              └──────────┬───────────┘
                         ▼
              ┌──────────────────────┐
              │   CPDO DEFAULTS      │
              │  Investors Lose $$$  │
              └──────────────────────┘



a relationship between spread and intensity
plug in spread and obtain lamda