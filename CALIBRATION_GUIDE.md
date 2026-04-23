# Health Scoring Calibration Guide
## How to Tune Thresholds for Production Deployment

---

## Overview

The algorithm as specified has **reasonable defaults** based on structural health monitoring literature. However, **thresholds should be calibrated** using:

1. **Pilot data** from known-good bridges (baseline variability)
2. **Insurance feedback** (what frequency shift do they care about?)
3. **Structural engineering expertise** (what does a 5% frequency drop actually mean?)

This guide walks through the calibration process for a pilot city.

---

## Phase 1: Baseline Characterization (Weeks 1–4)

**Goal**: Measure baseline frequency variability (σ_f) for each bridge type in your pilot region.

### 1.1 Select Test Bridges

Choose **2–3 known-healthy bridges** of each type in your pilot area:

| Bridge Type | Example | Location | Expected f | Notes |
|------------|---------|----------|------------|-------|
| Steel beam | Park Ave bridge | Downtown | 2–3 Hz | Stiff, low variability |
| Concrete beam | River crossing | East side | 1–2 Hz | Higher variability, temp-sensitive |
| Truss | Highway overpass | North | 3–5 Hz | Respond quickly to traffic |

**Healthy = no known defects, recent inspection passed.**

### 1.2 Collect Baseline Data

Deploy the app for **5–7 days** on each test bridge (recruit ~20–30 drivers):

- **Target**: 50+ valid trips per bridge (more is better)
- **Conditions**: Mixed weather, traffic, times of day
- **Quality gate**: Reject trips with c_freq < 0.6 (too noisy)

**Output**: Raw frequency measurements for each bridge.

### 1.3 Analyze Baseline Variability

For each bridge, compute:

```python
import numpy as np

frequencies = [...]  # 50+ measurements
f_mean = np.mean(frequencies)
f_std = np.std(frequencies)
f_cv = f_std / f_mean  # Coefficient of variation (%)

print(f"Bridge: {name}")
print(f"  Mean frequency: {f_mean:.2f} Hz")
print(f"  Std dev (σ_f): {f_std:.3f} Hz ({f_cv:.1f}%)")
print(f"  95% expected range: [{f_mean - 1.96*f_std:.2f}, {f_mean + 1.96*f_std:.2f}] Hz")
```

**Expected results** (from literature):

| Bridge Type | Typical σ_f | Typical σ_f % |
|------------|-----------|--------------|
| Steel, well-maintained | 0.03–0.08 Hz | 1–3% |
| Concrete, temperature-sensitive | 0.08–0.15 Hz | 3–8% |
| Truss, traffic-responsive | 0.10–0.20 Hz | 3–5% |

**If you measure σ_f > 0.25 Hz (10%+):**
- Bridge may be loose/damaged already
- High environmental sensitivity (wind, temperature)
- Consider excluding from baseline or investigating further

### 1.4 Document Bridge Characteristics

Create a **bridge profile**:

```yaml
Bridge: Golden Gate Main Span
Type: Suspension
Location: SF
BaselineFrequency: 2.45 Hz
BaselineStd: 0.07 Hz
BaselineTrips: 52
ProfileDate: 2025-05-15
Characteristics:
  - Well-maintained cables (visual inspection 2024)
  - Heavy traffic (avg 100k vehicles/day)
  - Windy exposure (coastal, high variance expected)
Notes: |
  Baseline variability (2.8%) is higher than steel beam bridges
  due to wind buffeting. Set thresholds accordingly.
```

---

## Phase 2: Establish Threshold Anchors (Week 4–5)

**Goal**: Decide what z_f values trigger Red/Yellow based on engineering judgment + insurance input.

### 2.1 Engage Structural Engineers

**Question for engineers:** "At what frequency drop would you be concerned?"

Typical responses:

| Scenario | Freq Drop | Concern Level |
|----------|-----------|---------------|
| Minor corrosion, no visual defects | 1–2% | Low |
| Visible rust, small hairline crack | 3–5% | Moderate |
| Active crack, obvious deflection | 5–10% | High |
| Severe damage, closure risk | >10% | Critical |

For a bridge with f_baseline = 2.5 Hz and σ_f = 0.08 Hz:

| Freq Drop | Hz | z_f | Our Category | Engineer Concern | Decision |
|-----------|-----|------|------------|-----------------|----------|
| 1% | 0.025 | 0.31 | Low | Low | ✓ Green threshold OK |
| 3% | 0.075 | 0.94 | Moderate | Moderate | Yellow boundary? |
| 5% | 0.125 | 1.56 | Moderate | Moderate-High | Red boundary? |
| 10% | 0.25 | 3.12 | Critical | High | ✓ Red threshold OK |

**Calibration rule**: Set Red threshold where engineer says "inspect now."

### 2.2 Engage Insurance Company

**Question for underwriters:** "What's your loss exposure tolerance?"

- **"If a bridge fails and we didn't warn you, what's the cost?"** → ~$500M
- **"How often can you tolerate a false positive?"** → ~1% of bridges (so 99% specificity)
- **"What's the value of early detection?"** → ~$10–50M (avoid catastrophe)

**Translation to thresholds:**
- If you can afford false positives, lower the Red threshold (z_f > 1.5 = more sensitive)
- If you need high specificity, raise it (z_f > 2.5 = fewer false alarms)

### 2.3 Propose Thresholds for Pilot

**Starting point** (conservative):

```
RED:    z_f > 2.0 AND variance_increase > 1.5
YELLOW: z_f > 1.0 OR variance_increase > 2.0
GREEN:  Otherwise
```

**Adjustment knobs**:
- Lower z_f threshold → more sensitive (catch smaller issues earlier)
- Raise z_f threshold → more specific (fewer false alarms)
- Increase variance multiplier → focus on frequency shift
- Decrease variance multiplier → flag instability more aggressively

---

## Phase 3: Pilot Deployment (Weeks 6–12)

**Goal**: Collect real data, measure false positive/negative rates, refine thresholds.

### 3.1 Deploy on 5–10 Bridges

Roll out to a mix:
- 2 known-good bridges (should stay Green)
- 1 bridge with minor known issues (should turn Yellow)
- 2 bridges with unknown condition (to discover baseline)

### 3.2 Weekly Threshold Review

Every week, compute:

```
Total trips: N
Red alerts: R
Yellow alerts: Y
Green: G = N - R - Y

Red false alarm rate: R / (number of red bridges that passed inspection) × 100%
Coverage: (R + Y) / N × 100%  # What fraction of trips detected anomalies?
```

**Expected outcomes**:
- Known-good bridges: 0% Red, < 5% Yellow
- Unknown bridges: 5–15% Red/Yellow (new baselines settling)

### 3.3 Collect Feedback

- **Structural engineers**: "Do the Red alerts match your concerns?"
- **Insurance**: "Are you comfortable with this sensitivity?"
- **City/DOT**: "Can you inspect flagged bridges within 48 hours?"

**Adjust thresholds** based on feedback:

| Feedback | Action |
|----------|--------|
| "Too many false alarms" | Raise z_f threshold (e.g., 2.0 → 2.5) |
| "Missing early issues" | Lower z_f threshold (e.g., 2.0 → 1.5) |
| "Variance changes are noise" | Increase variance multiplier (1.5 → 2.0) |
| "Variance signals real damage" | Decrease variance multiplier |

### 3.4 Document Calibration Evolution

```
Week 6: z_f > 2.0 triggers Red
  Feedback: 3 false alarms on stable bridges
  Action: Raise to z_f > 2.5

Week 8: z_f > 2.5 triggers Red
  Feedback: Almost no false alarms, but missed early warning on Bridge X
  Action: Add variance escalation (if Δv > 3.0, flag at z_f > 1.8)

Week 12: Final thresholds
  z_f > 2.5 (high confidence required)
  OR z_f > 1.8 AND Δv > 3.0 (joint risk)
  
  Result: 2% false positive rate, caught Bridge X issue at week 8
  Insurance approval: ✓ Acceptable
```

---

## Phase 4: Bridge-Specific Tuning (Optional, Week 12+)

**Advanced**: Different bridges may warrant different thresholds based on type and age.

### 4.1 Bridge Risk Profile

For each bridge, compute a **risk modifier**:

```
risk_factor = (age_years / 50) × (traffic_annual / 1M_vehicles) × structure_type_adjustment

Examples:
  Golden Gate (80yr, 100M traffic/yr, suspension): 1.6 → More sensitive (z_f > 1.5)
  New park bridge (5yr, 10k traffic/yr, concrete): 0.3 → Less sensitive (z_f > 3.0)
```

**Interpretation**: Older, high-traffic bridges should be monitored more closely.

### 4.2 Implement Bridge-Specific Thresholds

In the backend, replace global thresholds with bridge profiles:

```python
# Current (uniform):
if z_f > 2.0:
    health = 'Red'

# Advanced (per-bridge):
thresholds = load_bridge_profile(bridge_id)
if z_f > thresholds['red_threshold']:  # May be 1.5–3.0 depending on bridge
    health = 'Red'
```

---

## Phase 5: Ongoing Calibration (Post-Deployment)

### 5.1 Quarterly Review

Every 3 months, analyze:

1. **Distribution of alerts**:
   ```
   Bridges by health status:
     Green: 75%
     Yellow: 18%
     Red: 7%
   ```
   
   If Red > 10%, something is wrong (high baseline variability? seasonal effect?)

2. **Alert accuracy**:
   - Track which Red alerts resulted in actual defects (post-inspection)
   - Compute sensitivity & specificity

3. **Trend in baseline frequencies**:
   - Aggregate all trips by bridge type
   - Check if baseline is drifting year-over-year (seasonal? secular?)

### 5.2 Annual Calibration Meeting

Bring together:
- Engineers (structural assessment)
- Insurance (risk tolerance)
- Operations (can we handle alerts?)

Review and adjust thresholds if needed.

---

## Practical Checklist: Before Going Live

- [ ] Baseline data collected for ≥ 3 bridge types (50+ trips each)
- [ ] σ_f measured and documented for each type
- [ ] Structural engineers signed off on Red/Yellow thresholds
- [ ] Insurance approved acceptable false positive rate
- [ ] Pilot deployment completed (8+ weeks)
- [ ] At least 1 known-issue bridge flagged as expected
- [ ] Backend updated with final thresholds
- [ ] Alerts monitored 24/7 (someone responsible)
- [ ] Inspection SLA defined (< 48 hr for Red)
- [ ] Quarterly review process scheduled

---

## Example: Golden Gate Bridge Calibration

**Real-world walkthrough:**

### Baseline (Week 1–4)

50 trips collected over 2 weeks:

```
Frequencies: [2.43, 2.46, 2.48, 2.44, 2.49, ...]  Hz
Mean: 2.456 Hz
Std:  0.068 Hz (2.8%)
```

### Engagement (Week 4–5)

Engineer input: "Suspension bridges are sensitive. A 5% drop (0.12 Hz) would concern me."

That's z_f = 0.12 / 0.068 = 1.76σ.

Insurance: "We want high confidence. False alarms cost us credibility with the city. Set Red at z_f > 2.0."

### Pilot (Week 6–12)

- Week 6: Deploy thresholds (z_f > 2.0 = Red, z_f > 1.0 = Yellow)
- Week 8: Traffic spike → temporary 1.8σ shift on Yellow alert (false alarm, weather change)
- Week 10: Actual corrosion detected (by inspection): frequency shifted 2.3σ → Red alert caught it!
- Week 12: Final approval. Thresholds locked.

**Lesson**: Variance (weather, traffic) causes noise. Higher z_f threshold (> 2.0) filters it well.

---

## References

1. **Structural Health Monitoring**: Worden & Dulieu-Barton (2004). "An Overview of Intelligent Fault Detection."
2. **Modal Analysis**: Ewins (2000). "Modal Testing: Theory, Practice and Application."
3. **Bridge Monitoring Thresholds**: ASCE (2017). "Guidelines for Structural Health Monitoring."
4. **Risk-Based Thresholds**: Faber & Nathwani (2016). "Decision-making under uncertainty in civil engineering."

---

## Questions & Troubleshooting

**Q: My σ_f is 10%+ (very high variability). Why?**

A: Common causes:
- Environmental: high winds, large temperature swings, heavy traffic
- Measurement: low confidence (c_freq < 0.6), poor accelerometer placement
- Bridge: loose joints, non-linear damping, underestimated complexity

Solution: Filter out low-confidence measurements, collect data in calm conditions, or raise thresholds for this bridge type.

**Q: Should I use global thresholds or per-bridge thresholds?**

A: **Global** for simplicity, especially early (weeks 1–12). **Per-bridge** later if you have >20 monitored bridges and clear patterns (old bridges have higher thresholds, etc.).

**Q: What if a bridge fails the system can't predict?**

A: **This will happen.** Not all failures are vibration-based (e.g., fatigue crack initiation, sudden event). Use SHM as one input, not the only one. Combine with:
- Periodic visual inspections
- Weather alerts (heavy rain → scour risk)
- Load monitoring (unusual traffic patterns)

**Q: How often should I recalibrate?**

A: **Annually minimum**. More frequently if:
- New bridge type added
- Major structural work (retrofit, repair)
- New insurance partnership with different risk tolerance
- System catches a real failure (validate thresholds worked!)

