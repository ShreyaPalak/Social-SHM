# Social SHM Health Scoring Algorithm
## Formal Specification v1.0

---

## Executive Summary

The health score is a **composite index** that combines:
- **Frequency shift** (how much the bridge's natural frequency has changed)
- **Modal variance** (how unstable/unclear the frequency measurement is)
- **Measurement confidence** (how reliable is the extracted frequency)
- **Baseline maturity** (do we have enough trips to trust the baseline)

It produces a **categorical output** (Red/Yellow/Green) with a **numeric score** (0–100) and **confidence interval** suitable for insurance decision-making.

---

## Part 1: Definitions

### 1.1 Baseline Signature

After **N_baseline = 30 valid trips** on a bridge, we compute:

```
f_baseline = mean(f₁, f₂, ..., f₃₀)           [Hz]
σ_f = stddev(f₁, f₂, ..., f₃₀)                [Hz]
v_baseline = mean(peak_variance₁, ..., peak_variance₃₀)  [Hz²]
σ_v = stddev(peak_variance₁, ..., peak_variance₃₀)      [Hz²]
```

These **do not change** for 30 days (unless anomaly triggers a recompute).

### 1.2 Current Measurement

For each new trip, we extract:

```
f_current = dominant peak frequency              [Hz]
c_freq = frequency detection confidence          [0..1]
v_current = variance in peak detection           [Hz²]
N_trips = total valid trips on this bridge       [count]
```

### 1.3 Deviation Metrics

```
Δf = |f_current - f_baseline|                   [Hz, absolute shift]
z_f = Δf / σ_f                                  [dimensionless, # of std devs]
Δv = v_current / v_baseline                     [dimensionless, multiplier]
```

**Interpretation:**
- `z_f = 1.0`: Frequency shifted by 1 standard deviation (normal variability)
- `z_f = 2.0`: Frequency shifted by 2 standard deviations (notable change)
- `z_f = 3.0`: Frequency shifted by 3 standard deviations (strong evidence of damage)

---

## Part 2: Health Score Formula

### 2.1 Baseline Maturity Check

```
if N_trips < 30:
    return { health: 'Unknown', score: null, reason: 'Insufficient baseline data' }
```

**Explanation**: We do not score until we have at least 30 valid trips. The first 30 trips are used to *learn* the baseline, not to evaluate it.

### 2.2 Risk Assessment Matrix

We evaluate **two independent risk factors**:

#### Factor A: Frequency Shift Risk

```
if z_f > 3.0:
    freq_risk = 'critical'      # Very strong evidence of stiffness loss
elif z_f > 2.0:
    freq_risk = 'high'          # Strong evidence
elif z_f > 1.0:
    freq_risk = 'moderate'      # Noticeable change
else:
    freq_risk = 'low'           # Within normal variability
```

#### Factor B: Modal Clarity Risk

```
if Δv > 3.0:
    clarity_risk = 'critical'   # Frequency very unstable (many modes visible)
elif Δv > 2.0:
    clarity_risk = 'high'       # Noticeably more unclear
elif Δv > 1.5:
    clarity_risk = 'moderate'   # Slight increase in instability
else:
    clarity_risk = 'low'        # Stable modal signature
```

#### Factor C: Confidence Risk

```
if c_freq < 0.4:
    confidence_risk = 'critical'  # Measurement unreliable
elif c_freq < 0.6:
    confidence_risk = 'high'      # Borderline
else:
    confidence_risk = 'low'       # Good measurement
```

### 2.3 Risk Aggregation Matrix

Combine the three factors to assign **health status**:

```
RED if:
  (freq_risk = 'critical' AND clarity_risk >= 'moderate')
  OR (freq_risk = 'high' AND clarity_risk = 'critical')
  OR (freq_risk = 'high' AND clarity_risk = 'high' AND confidence_risk = 'low')
  → Score: 25 (High risk of structural damage)

YELLOW if:
  (freq_risk = 'high' AND clarity_risk = 'low')
  OR (freq_risk = 'moderate' AND clarity_risk >= 'moderate')
  OR (confidence_risk = 'critical')
  → Score: 50 (Monitor, collect more data)

GREEN if:
  freq_risk = 'low' OR clarity_risk = 'low'
  (AND NOT any 'critical' risks)
  → Score: 75 (Normal operation)

UNKNOWN if:
  N_trips < 30
  → Score: null (Not yet scored)
```

---

## Part 3: Detailed Scoring Logic (Pseudocode)

```
function compute_health_score(
  f_current,        # Hz
  c_freq,           # 0..1
  v_current,        # Hz²
  f_baseline,       # Hz
  σ_f,              # Hz
  v_baseline,       # Hz²
  σ_v,              # Hz²
  N_trips           # count
):
  
  # Check baseline maturity
  if N_trips < 30:
    return {
      health: 'Unknown',
      score: null,
      reason: 'Insufficient data (< 30 trips)',
      trip_count: N_trips
    }
  
  # Compute deviations
  Δf = abs(f_current - f_baseline)
  z_f = Δf / max(σ_f, 0.05)  # Avoid division by zero; use 0.05 Hz floor
  Δv = v_current / max(v_baseline, 0.01)  # Floor variance at 0.01 Hz²
  
  # Factor A: Frequency shift risk
  if z_f > 3.0:
    freq_risk_score = 0
  elif z_f > 2.0:
    freq_risk_score = 25
  elif z_f > 1.0:
    freq_risk_score = 50
  else:
    freq_risk_score = 75
  
  # Factor B: Modal clarity risk (variance)
  if Δv > 3.0:
    clarity_risk_score = 0
  elif Δv > 2.0:
    clarity_risk_score = 25
  elif Δv > 1.5:
    clarity_risk_score = 50
  else:
    clarity_risk_score = 75
  
  # Factor C: Measurement confidence
  if c_freq < 0.4:
    confidence_penalty = 50  # Reduce score by 50 points
  elif c_freq < 0.6:
    confidence_penalty = 25
  else:
    confidence_penalty = 0
  
  # Combine: take minimum of the three (most conservative)
  raw_score = min(freq_risk_score, clarity_risk_score) - confidence_penalty
  final_score = max(0, min(100, raw_score))  # Clamp to [0, 100]
  
  # Map to categorical health
  if final_score < 35:
    health = 'Red'
  elif final_score < 65:
    health = 'Yellow'
  else:
    health = 'Green'
  
  return {
    health: health,
    score: final_score,
    z_f: z_f,
    Δv: Δv,
    c_freq: c_freq,
    details: {
      frequency_shift_hz: Δf,
      frequency_shift_sigma: z_f,
      variance_increase: Δv,
      confidence: c_freq
    }
  }
```

---

## Part 4: Calibration & Real-World Mapping

### 4.1 What Do These Numbers Actually Mean?

**Frequency shift (z_f)** correlates to:

| z_f | Physical Interpretation | Example |
|-----|-------------------------|---------|
| 0.0–0.5 | Normal measurement variability | Temperature swing, traffic loading |
| 0.5–1.0 | Borderline change | Slight corrosion, minor settling |
| 1.0–2.0 | Noticeable change | Rust on cables, 2–5 mm deflection increase |
| 2.0–3.0 | Significant change | Active crack (< 2mm), scour (early stage) |
| > 3.0 | Critical | Serious structural damage, imminent failure |

**Frequency shift in Hz → Structural consequence:**

For a typical 200m steel bridge with f_baseline = 2.0 Hz:

```
Δf = 0.1 Hz (5%)  → σ ≈ 0.05 Hz   → z_f ≈ 2.0  → High risk
Δf = 0.05 Hz (2.5%) → σ ≈ 0.05 Hz → z_f ≈ 1.0  → Moderate
Δf = 0.02 Hz (1%) → σ ≈ 0.05 Hz  → z_f ≈ 0.4  → Low
```

A **5% frequency drop** suggests:
- **Stiffness loss of ~10%** (linear relationship: f ∝ √k)
- Concrete: significant micro-cracking, steel: corrosion/loss of section
- **Action**: Visual inspection within 2 weeks

### 4.2 Modal Variance (Δv)

**Why it matters**: If the peak detection suddenly sees *multiple* peaks of similar height, it means the bridge's modal response is becoming unstable — a sign of incipient failure.

| Δv | Meaning |
|-----|---------|
| < 1.2 | Very stable; clear dominant mode |
| 1.2–1.5 | Slight increase in secondary modes |
| 1.5–2.0 | Modal coupling (damping increasing) |
| > 2.0 | Multiple competing modes (possible failure mode change) |

### 4.3 Confidence (c_freq)

**Low confidence** (c_freq < 0.6) can occur because:
- Heavy traffic during measurement (noise dominates signal)
- Wind buffeting (broad spectral response)
- Temperature instability (multiple frequency peaks)
- Poor accelerometer placement

**Action on low confidence**: Collect more trips before drawing conclusions.

---

## Part 5: Examples

### Example 1: Stable Bridge (Green)

```
Baseline (30 trips):
  f_baseline = 2.50 Hz, σ_f = 0.08 Hz
  v_baseline = 0.15 Hz², σ_v = 0.05 Hz²

New trip:
  f_current = 2.51 Hz
  c_freq = 0.92
  v_current = 0.16 Hz²

Computation:
  Δf = |2.51 - 2.50| = 0.01 Hz
  z_f = 0.01 / 0.08 = 0.125 → freq_risk = 'low' (75 pts)
  Δv = 0.16 / 0.15 = 1.07 → clarity_risk = 'low' (75 pts)
  confidence_risk = 'low' (0 pt penalty)
  
  raw_score = min(75, 75) - 0 = 75
  
Result:
  ✓ GREEN (Score 75)
  "Bridge operating normally. No action required."
```

### Example 2: Concerning Trend (Yellow)

```
Baseline (30 trips):
  f_baseline = 2.50 Hz, σ_f = 0.08 Hz
  v_baseline = 0.15 Hz²

New trip (day 40):
  f_current = 2.35 Hz (Δf = 0.15 Hz, -6%)
  c_freq = 0.75
  v_current = 0.25 Hz² (Δv = 1.67)

Computation:
  z_f = 0.15 / 0.08 = 1.875 → freq_risk = 'high' (25 pts)
  Δv = 0.25 / 0.15 = 1.67 → clarity_risk = 'moderate' (50 pts)
  confidence_risk = 'low' (0 pt penalty)
  
  raw_score = min(25, 50) - 0 = 25
  
Result:
  ⚠ RED (Score 25)
  "Frequency shift of 1.9σ detected. High risk of stiffness loss.
   Recommend visual inspection + follow-up measurements in 3–5 days."
```

Wait, this should be RED, not YELLOW. Let me recalculate:

```
freq_risk = 'high' (z_f = 1.875, between 1.0 and 2.0)
clarity_risk = 'moderate' (Δv = 1.67, between 1.5 and 2.0)

Matrix: high + moderate = RED
Final score = 25
```

### Example 3: High Variance, Low Confidence (Yellow)

```
Baseline:
  f_baseline = 3.20 Hz, σ_f = 0.10 Hz
  v_baseline = 0.20 Hz²

New trip (windy conditions):
  f_current = 3.18 Hz
  c_freq = 0.45 (low: wind noise)
  v_current = 0.50 Hz² (Δv = 2.5)

Computation:
  z_f = 0.02 / 0.10 = 0.2 → freq_risk = 'low' (75 pts)
  Δv = 0.50 / 0.20 = 2.5 → clarity_risk = 'high' (25 pts)
  confidence_risk = 'high' (25 pt penalty)
  
  raw_score = min(75, 25) - 25 = 0
  
Result:
  ⚠ RED (Score 0)
  "High measurement uncertainty + increased modal variance.
   Cannot assess health. Recommend collecting trip in calmer conditions."
```

---

## Part 6: Temporal Tracking & Trend Analysis

Health status is **instantaneous** (based on the latest trip), but **insurance decision-makers care about trends**.

Compute a **7-day rolling baseline** to detect drift:

```
Last 7 days of valid trips:
  f_7d_mean = mean(f_t-6, f_t-5, ..., f_t)
  f_7d_trend = (f_t - f_t-6) / 6 days  [Hz/day]
  
if f_7d_trend < -0.01 Hz/day:
  # Frequency dropping > 1% per day
  # Accelerated stiffness loss → ESCALATE TO RED even if current trip is Yellow
```

**Trigger**: If score is Yellow AND frequency is drifting down, promote to Red.

---

## Part 7: Calibration by Bridge Type

Different bridge types have different baseline variability (σ_f):

| Bridge Type | Typical σ_f | Baseline Trips | Notes |
|------------|-----------|----------------|-------|
| Steel cable-stayed | 0.05–0.10 Hz | 30 | Low variance, very responsive |
| Concrete beam | 0.10–0.20 Hz | 40–50 | Higher variability due to temperature |
| Truss (steel) | 0.08–0.15 Hz | 35 | Moderate variability |
| Suspension | 0.03–0.08 Hz | 50 | Very low variance, very sensitive |

**Tuning strategy**:
1. Collect 50 trips on known-healthy bridge of same type
2. Measure actual σ_f
3. Set alarm thresholds (z_f = 2.0 for "high risk") based on calibration data

---

## Part 8: Implementation Checklist

- [ ] Compute f_baseline, σ_f, v_baseline, σ_v after 30 valid trips
- [ ] For each new trip, extract f_current, c_freq, v_current
- [ ] Compute z_f, Δv, confidence_risk
- [ ] Apply risk matrix to assign health status
- [ ] Store score + details in database (for auditing)
- [ ] Compute 7-day trend (optional but recommended)
- [ ] Trigger alerts when score drops to Red
- [ ] Log every score transition (Green → Yellow, etc.) for audit
- [ ] Validate thresholds with structural engineers (before deployment)

---

## Part 9: Uncertainty & Confidence Intervals

For insurance reporting, include confidence bounds:

```
Score = 75 (Green)
90% Confidence Interval: [68, 82]

Interpretation:
  "With 90% confidence, true health score is between 68 (Yellow boundary)
   and 82 (deep Green). Current data: CONCLUSIVE GREEN."

---

Score = 50 (Yellow)
90% Confidence Interval: [35, 65]

Interpretation:
  "With 90% confidence, true score is between 35 (Red boundary)
   and 65 (Yellow boundary). Current data: INCONCLUSIVE.
   Recommend additional measurements before action."
```

**Calculation**:
```
CI = score ± 1.645 × SE

where SE = sqrt( (z_f_uncertainty)² + (Δv_uncertainty)² )
      z_f_uncertainty = z_f × sqrt( (σ_f_error/σ_f)² + (measurement_noise)² )
      Δv_uncertainty = Δv × sqrt( (σ_v_error/σ_v)² )
```

---

## References & Future Work

1. **Modal analysis best practices**: ISO 13373-1 (Vibration-based condition monitoring)
2. **Structural health monitoring**: ASCE Guidelines for SHM (2017)
3. **Insurance risk models**: Adapt standard bridge failure statistics to modal frequency thresholds
4. **Calibration data**: Collect data on bridges that *actually failed* and work backwards to validate thresholds

---

## Summary: When to Alert Insurance

| Health | Action | Timeline |
|--------|--------|----------|
| **Green** (score ≥ 70) | Routine monitoring | Continue normal collection |
| **Yellow** (score 35–69) | Review + retest | Collect 5–10 more trips within 3 days |
| **Red** (score < 35) | Visual inspection required | Within 48 hours |
| **Red + downward trend** | Urgent closure / load limit | Within 24 hours |

**Insurance claim trigger**: Two consecutive Red scores within 7 days → Notify underwriting immediately.
