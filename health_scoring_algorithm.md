# Social SHM Health Scoring Algorithm
## Formal Specification v1.0

---

## Executive Summary

The health score is a **two-dimensional risk model** based on:

1. **Frequency Shift** (Δf) — how much the bridge's natural frequency has changed from baseline
2. **Variance Increase** (Δσ) — loss of modal clarity (unstable/degrading structure)

Together, these indicate **structural stiffness loss** (primary failure mode for bridges: cracks, scour, corrosion).

**Score Range**: 0–100
- **Green (75–100)**: Normal operation, low risk
- **Yellow (30–74)**: Moderate warning, increased monitoring recommended
- **Red (0–29)**: Critical alert, immediate inspection required

---

## Mathematical Framework

### 1. Baseline Computation

After **N ≥ 30 valid trips** on a bridge, the backend computes baseline statistics:

```
f_baseline = mean(dominant_frequency across N trips)
σ_f = stddev(dominant_frequency across N trips)

v_baseline = mean(peak_variance across N trips)
σ_v = stddev(peak_variance across N trips)

confidence_baseline = N / 50  (normalized to 0..1, capped at 1 when N ≥ 50)
```

**Rationale**: 
- 30 trips = ~6–10 days of commuter traffic on a bridge (minimal variability)
- 50+ trips = locked-in signature (high confidence)
- Both frequency mean and variance matter (first derivative = stiffness, second = instability)

### 2. Single-Trip Risk Metrics

For each new trip, compute two normalized deviations:

#### A. Frequency Shift (Δf)

```
Δf_raw = |f_current - f_baseline|

z_freq = Δf_raw / σ_f   (units: standard deviations)
```

**Interpretation**:
- `z_freq = 0.5`: Frequency is 0.5σ from baseline (normal noise)
- `z_freq = 1.0`: Frequency is 1σ from baseline (noticeable shift, but within 1 std)
- `z_freq = 2.0`: Frequency is 2σ from baseline (rare, 2.3% probability if normal distribution)
- `z_freq > 2.5`: Significant structural change

#### B. Variance Increase (Δσ)

```
Δσ_raw = v_current / v_baseline   (ratio, not difference)

If v_baseline is very small (unstable baseline), use floor: Δσ_raw = max(1.0, ratio)
```

**Interpretation**:
- `Δσ = 1.0`: Variance unchanged (stable)
- `Δσ = 1.5`: Variance increased 50% (loss of clarity)
- `Δσ = 2.0`: Variance doubled (significant instability)
- `Δσ > 2.5`: Imminent failure signature

### 3. Health Score Function

The score is computed in two stages:

#### Stage 1: Individual Risk Signals

```python
def risk_from_frequency(z_freq):
    """
    Convert frequency z-score to risk (0..1).
    Smooth sigmoid curve: gradual increase in risk as shift grows.
    """
    if z_freq < 0.5:
        return 0.0  # Normal noise
    
    # Sigmoid function: smooth transition from 0 to 1
    # 50% risk at z=1.5, 95% risk at z=3.0
    risk_freq = 1 / (1 + exp(-(z_freq - 1.5) / 0.5))
    return min(risk_freq, 1.0)

def risk_from_variance(delta_sigma):
    """
    Convert variance ratio to risk (0..1).
    """
    if delta_sigma < 1.2:
        return 0.0  # Normal fluctuation
    
    # Linear ramp: 0 risk at 1.2x, 100% risk at 2.5x baseline
    risk_var = max(0, (delta_sigma - 1.2) / (2.5 - 1.2))
    return min(risk_var, 1.0)
```

#### Stage 2: Combined Risk Score

```python
def compute_health_score(z_freq, delta_sigma, confidence_baseline):
    """
    Combine individual risk signals into a single 0-100 score.
    
    Confidence weighting: if baseline is weak (<30 trips), rely more on jerk detection.
    If baseline is strong (50+ trips), use full algorithm.
    """
    risk_freq = risk_from_frequency(z_freq)
    risk_var = risk_from_variance(delta_sigma)
    
    # Combine risks with AND logic (both must be high for critical alert)
    # BUT: if one is very high, override
    if risk_freq > 0.95 or risk_var > 0.95:
        combined_risk = max(risk_freq, risk_var)  # Override threshold
    else:
        # Weighted average: frequency shift is primary indicator (60% weight)
        combined_risk = 0.6 * risk_freq + 0.4 * risk_var
    
    # Apply confidence penalty: if baseline is weak, boost caution
    # Low confidence (N=30) → penalize score by -10
    # High confidence (N≥50) → no penalty
    confidence_penalty = (1 - confidence_baseline) * 10  # 0..10 point deduction
    
    # Convert risk (0..1) to score (0..100), inverted
    score = 100 * (1 - combined_risk) - confidence_penalty
    
    return max(0, min(100, score))  # Clamp to [0, 100]

def health_status(score):
    if score >= 75:
        return 'Green'
    elif score >= 30:
        return 'Yellow'
    else:
        return 'Red'
```

---

## Threshold Decision Table

| Scenario | z_freq | Δσ | Baseline | Result | Rationale |
|----------|--------|-----|----------|--------|-----------|
| **Normal operation** | 0.2 | 1.0 | N=50 | Green (92) | No frequency shift, stable variance |
| **Measurement noise** | 0.8 | 1.1 | N=50 | Green (85) | Small shifts within ±1σ are normal |
| **Minor alert** | 1.5 | 1.4 | N=50 | Yellow (58) | 1.5σ shift + 40% variance increase |
| **Moderate alert** | 2.0 | 1.8 | N=50 | Yellow (42) | 2σ shift + 80% variance increase |
| **Severe alert** | 2.5 | 2.2 | N=50 | Red (15) | 2.5σ shift + 120% variance increase |
| **Critical alert** | 3.0 | 2.5 | N=50 | Red (5) | Extreme frequency shift + high instability |
| **Weak baseline** | 1.2 | 1.3 | N=25 | Yellow (45) | Same risk metrics, but lower confidence |

---

## Failure Mode Mapping

| Bridge Failure | Expected Signature | z_freq | Δσ |
|---|---|---|---|
| **Hairline crack (early)** | Stiffness loss, stable modes | 1.0–1.5 | 1.2–1.5 |
| **Crack (propagating)** | Significant stiffness loss, mode splitting | 2.0–2.5 | 1.5–2.0 |
| **Scour (foundation)** | Dramatic frequency drop, mode confusion | 2.5–3.5 | 2.0–2.5 |
| **Corrosion (cables/joints)** | Frequency drift + damping increase | 1.5–2.5 | 1.8–2.5 |
| **Temporary: vehicle mass** | Frequency drop only, variance stable | 1.0–2.0 | <1.2 |
| **Temporary: wind/weather** | Both shift + variance, then revert | 1.5–2.5 | 1.5–2.0 |

**Key insight**: Structural damage shows **both** frequency shift AND variance increase. Environmental factors often show only one or neither.

---

## Baseline Stability & Confidence

### Baseline Lock-In Timeline

| Trips | Days (est.) | Confidence | Status |
|-------|-------------|-----------|--------|
| 10–20 | 2–4 | "Learning" (score disabled) | Do not compute health yet |
| 20–30 | 4–7 | 66% | Compute score, but interpret cautiously |
| 30–50 | 7–14 | 76–100% | Baseline locked, full algorithm active |
| 50+ | 14+ | 100% | Confident baseline; algorithm fully calibrated |

**Rule**: Do not compute health scores until **N ≥ 20**. Before that, only use jerk detection.

### Baseline Drift Handling

If the baseline itself appears to be drifting (e.g., seasonal temperature changes), recompute baseline quarterly:

```python
def should_recompute_baseline(trips_past_90_days, trips_total):
    """
    If last 90 days show significant divergence from all-time baseline,
    recompute with recent data only (more responsive to real changes).
    """
    if trips_past_90_days < 15:
        return False  # Not enough recent data
    
    recent_mean = mean(trips_past_90_days.frequency)
    overall_mean = mean(trips_total.frequency)
    
    if abs(recent_mean - overall_mean) > 2 * overall_std:
        return True  # Drift detected, re-baseline
    
    return False
```

---

## Insurance-Friendly Reporting

### Risk Score Conversion for Actuaries

Convert health score to **bridge repair cost risk**:

```python
def annual_cost_risk(health_status, bridge_age_years, avg_aadt):
    """
    Estimate expected annual repair/replacement costs (in units of $100k).
    Inputs:
      health_status: 'Green', 'Yellow', 'Red'
      bridge_age_years: age of bridge
      avg_aadt: Average Annual Daily Traffic
    """
    base_cost = 0
    
    if health_status == 'Green':
        base_cost = 0.05 * (bridge_age_years / 50)  # Minimal risk
    elif health_status == 'Yellow':
        base_cost = 0.30 * (bridge_age_years / 50)  # Monitoring costs
    else:  # Red
        base_cost = 1.50 * (bridge_age_years / 50)  # Repair/failure costs
    
    # Traffic-weighted: high-traffic bridges = higher consequence
    traffic_multiplier = 1 + (avg_aadt / 50000)  # Normalized to 50k AADT
    
    return base_cost * traffic_multiplier
```

**Example**:
- Golden Gate Bridge: Red alert, 70 years old, 120k AADT
- Risk = 1.50 * (70/50) * (1 + 120k/50k) = **$12.6M/year** expected cost

This is the **value proposition** for insurance companies: avoid catastrophic failures.

---

## Calibration & Tuning

### Sensitivity Analysis: How to Adjust Thresholds

```python
def sensitivity_analysis():
    """
    Test how score changes with parameter variations.
    Use this to calibrate after collecting real-world failure data.
    """
    test_cases = [
        {'z_freq': 1.5, 'delta_sigma': 1.4, 'expected_health': 'Yellow'},
        {'z_freq': 2.0, 'delta_sigma': 1.8, 'expected_health': 'Yellow'},
        {'z_freq': 2.5, 'delta_sigma': 2.2, 'expected_health': 'Red'},
    ]
    
    for case in test_cases:
        score = compute_health_score(case['z_freq'], case['delta_sigma'], 1.0)
        status = health_status(score)
        
        if status == case['expected_health']:
            print(f"✓ Pass: z_freq={case['z_freq']}, delta_sigma={case['delta_sigma']} → {status}")
        else:
            print(f"✗ FAIL: Expected {case['expected_health']}, got {status}")
            print(f"        Adjust sigmoid curves or thresholds")
```

### When to Re-Calibrate

1. **After first failure**: If a Red-alert bridge fails → validate thresholds
2. **After 100+ bridges**: Enough data to see if Yellow alerts correlate with repairs
3. **Annually**: Review false positive/negative rates with insurance claims data

---

## Implementation Checklist

- [ ] Baseline computation: mean frequency + std + variance (N ≥ 30)
- [ ] Z-score calculation for frequency shift
- [ ] Variance ratio calculation
- [ ] Sigmoid risk curves (configurable via environment)
- [ ] Combined risk logic (AND vs weighted average)
- [ ] Confidence weighting (based on N)
- [ ] Health status determination (Green/Yellow/Red)
- [ ] Insurance cost mapping (optional)
- [ ] Sensitivity analysis framework
- [ ] Logging/auditing of score changes (for legal defensibility)

---

## Next Steps After Deployment

1. **Pilot Phase (Month 1–3)**: Collect baseline on 20+ bridges
2. **Validation Phase (Month 3–6)**: Compare alerts to engineering inspections
3. **Calibration Phase (Month 6–12)**: Adjust thresholds based on validation data
4. **Production (Year 1+)**: Full deployment with insurance integration

**Success Metric**: Yellow/Red alerts should correlate with engineering findings at >85% accuracy.

---

## References

- **ISO 13373-2**: Condition monitoring and diagnostics – Vibration condition monitoring – Part 2: Vibration diagnostics
- **ASCE Infrastructure Report Card**: Bridge condition assessment frameworks
- **Bendat & Piersol (2010)**: Random Data: Analysis and Measurement Procedures
