# Health Scoring Integration Guide

## How It All Fits Together

The health scoring algorithm is the **decision engine** of Social SHM. Here's how the pieces connect:

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 1: Phone (Edge)                                           │
│ ✓ Accelerometer samples → Raw trip data                        │
└────────────────────────┬────────────────────────────────────────┘
                         │ POST /api/trips/upload
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ Layer 2: Backend (Cloud)                                        │
│ ✓ Signal processing: FFT, peak detection, jerk filtering       │
│ ✓ Extract: dominant_frequency, peak_variance                   │
│ ✓ Compare to baseline (if N ≥ 20)                              │
│ ✓ HEALTH SCORING ALGORITHM (THIS MODULE)                       │
│   └─ z_freq, Δσ → risk signals → combined risk → 0..100 score │
│ ✓ Store score + status (Green/Yellow/Red) in database          │
└────────────────────────┬────────────────────────────────────────┘
                         │ GET /api/bridges/:id/health
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ Layer 3: Dashboard (Visualization)                              │
│ ✓ Mapbox pins: Green/Yellow/Red based on health scores        │
│ ✓ Click to drill down: frequency history, confidence, costs    │
│ ✓ Export to insurance systems                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## The Algorithm in Context

### Input: Trip Analysis Results (from Backend Signal Processing)

```python
TripAnalysis(
    dominant_frequency=2.49,  # Hz, extracted from FFT peaks
    peak_variance=0.21,       # Normalized variance metric
    jerk_score=0.3,           # Already used to reject outliers
    confidence_freq=0.8       # How confident is frequency extraction
)
```

### Input: Learned Baseline (from PostgreSQL)

```python
BaselineStats(
    mean_frequency=2.34,      # Hz, from 30–50 valid trips
    std_frequency=0.10,       # Natural variation baseline
    mean_variance=0.15,       # Average variance
    trip_count=42             # 42 trips analyzed so far
)
```

### Output: Health Score

```python
HealthScore(
    score=64,                           # 0..100
    status=HealthStatus.YELLOW,         # Green/Yellow/Red
    z_freq=1.50,                        # 1.5 standard deviations shift
    delta_sigma=1.40,                   # 40% variance increase
    risk_frequency=0.50,                # 50% risk from frequency
    risk_variance=0.15,                 # 15% risk from variance
    combined_risk=0.39,                 # Weighted combination
    baseline_confidence=0.84,           # 84% confident (42 trips)
    rationale="significant frequency shift (1.50σ); variance increased..."
)
```

---

## Integration Checkpoints

### 1. In the Backend (server.js)

The backend currently has a stub health scorer. Replace it with:

```javascript
// server.js - POST /api/trips/upload endpoint

const { HealthScorer, BaselineStats, TripAnalysis } = require('./health_scorer.js');

// Inside the endpoint:
const scorer = new HealthScorer();

// After signal processing (FFT, peak detection):
const tripAnalysis = new TripAnalysis(
  dominantFreq,      // from detectPeaks()
  peakVariance,      // computed from peaks
  jerk.jerkScore,    // from detectJerk()
  freqConfidence
);

// Fetch baseline from DB
const baseline = await getBaseline(bridgeId);  // Returns BaselineStats or null

// Compute health score
const healthScore = scorer.compute_score(tripAnalysis, baseline);

// Store in database
await db.query(
  `INSERT INTO bridge_health (bridge_id, score, health_status, ...)
   VALUES ($1, $2, $3, ...)`,
  [bridgeId, healthScore.score, healthScore.status.toString()]
);
```

### 2. Thresholds (Environment Variables)

Configure sigmoid thresholds in `.env`:

```bash
# Health Scoring Parameters
FREQ_THRESH_LOWER=0.5          # z-score below which risk ≈ 0
FREQ_THRESH_UPPER=1.5          # z-score above which risk ≈ 1
VAR_THRESH_LOWER=1.2           # variance ratio lower bound
VAR_THRESH_UPPER=2.5           # variance ratio upper bound
FREQ_WEIGHT=0.6                # weight of frequency signal (vs variance)
VAR_WEIGHT=0.4                 # weight of variance signal

# Red/Yellow/Green Cutoffs
GREEN_SCORE_MIN=75
YELLOW_SCORE_MIN=30
RED_SCORE_MAX=29
```

### 3. Dashboard Integration

The dashboard queries `/api/bridges` and receives:

```json
{
  "id": "bridge-uuid",
  "name": "Golden Gate Bridge",
  "latitude": 37.8199,
  "longitude": -122.4783,
  "health_status": "Yellow",
  "score": 64,
  "trip_count": 42,
  "lastComputed": "2025-04-23T14:30:00Z"
}
```

**Rendering Logic**:
- `score >= 75` → Pin color: GREEN
- `30 <= score < 75` → Pin color: YELLOW
- `score < 30` → Pin color: RED
- `score == null` → Pin color: GRAY (baseline not ready)

### 4. Insurance Reporting

Export bridge health to insurance systems:

```python
def generate_insurance_report(bridge_id: str) -> dict:
    """
    Generate report for insurance underwriting systems.
    """
    health = db.query_bridge_health(bridge_id)
    
    cost_risk = annual_cost_risk(
        health['status'],
        bridge_age_years,
        average_daily_traffic
    )
    
    return {
        "bridgeId": bridge_id,
        "bridgeName": health['name'],
        "healthStatus": health['status'],
        "healthScore": health['score'],
        "confidenceLevel": health['confidence'],
        "estimatedAnnualRisk": f"${cost_risk}M",
        "lastUpdated": health['lastComputed'],
        "recommendations": [
            "Annual inspection" if health['status'] == 'Yellow' else
            "Immediate inspection" if health['status'] == 'Red' else
            "Routine monitoring"
        ]
    }
```

---

## Validation & Calibration Workflow

### Phase 1: Pilot (Month 1–3)

1. Deploy to 20 bridges
2. Collect 30–50 baseline trips each (1–2 weeks of traffic)
3. Verify scores are stable and reasonable
4. **Action**: Manually inspect a Yellow/Red bridge to validate algorithm

### Phase 2: Refinement (Month 3–6)

1. Collect actual failure/repair data
2. Compare alerts to engineering findings
3. **Calibration**: If False Positive Rate (FPR) > 20%, adjust thresholds:
   - Too many false yellows? → Increase `FREQ_THRESH_LOWER`
   - Too few true reds? → Decrease `VAR_THRESH_UPPER`
4. **Validation**: Target >85% accuracy on known failures

### Phase 3: Production (Month 6+)

1. Deploy to 100+ bridges
2. Continuous monitoring: track alert correlation with repairs
3. Quarterly re-calibration using latest failure data
4. Annual review with insurance partners

---

## Testing the Algorithm Locally

### 1. Run the test suite

```bash
python3 health_scorer.py
```

Output:
```
✓ Test 1: Normal operation → Score: 100/100 (Green)
✓ Test 2: Measurement noise → Score: 88/100 (Green)
✓ Test 3: Minor alert → Score: 64/100 (Yellow)
...
✓ All tests passed. Algorithm is ready for deployment.
```

### 2. Interactive calibration

Use the Python module in a Jupyter notebook:

```python
from health_scorer import HealthScorer, BaselineStats, TripAnalysis

scorer = HealthScorer(
    freq_thresh_lower=0.5,
    freq_thresh_upper=1.5,
    var_thresh_lower=1.2,
    var_thresh_upper=2.5
)

baseline = BaselineStats(2.34, 0.10, 0.15, 0.03, 50)
trip = TripAnalysis(2.49, 0.21, 0.3, 0.8)

score = scorer.compute_score(trip, baseline)
print(f"Score: {score.score} ({score.status.value})")
print(f"Rationale: {score.rationale}")
```

### 3. Sensitivity analysis

Re-run with different thresholds:

```python
for freq_lower in [0.4, 0.5, 0.6]:
    for var_lower in [1.0, 1.2, 1.4]:
        scorer = HealthScorer(
            freq_thresh_lower=freq_lower,
            var_thresh_lower=var_lower
        )
        # Re-test all cases
        # Compare: how many green → yellow conversions?
```

---

## Deployment Checklist

- [ ] Backend server has access to `health_scorer.py` (or equivalent Node.js module)
- [ ] Environment variables set in `.env` for all thresholds
- [ ] Database schema includes `bridge_health` table with `score` and `health_status` columns
- [ ] POST `/api/trips/upload` endpoint calls scorer after signal processing
- [ ] Baseline computed automatically after 30 valid trips (PostgreSQL trigger active)
- [ ] Dashboard fetches `/api/bridges` and renders Green/Yellow/Red pins
- [ ] Health score history logged to database for audit trail
- [ ] Sensitivity tests run: confirm no unexpected score changes
- [ ] Insurance reporting endpoint ready (`/api/reports/health/:bridgeId`)
- [ ] Monitoring alerts set up: notify ops when new Red bridges appear

---

## Expected Behavior

### Scenario 1: Bridge in Good Condition

- Baseline: 50 trips, mean frequency = 2.34 Hz, std = 0.10 Hz
- New trip: frequency = 2.35 Hz
- z_freq = 0.1, delta_sigma = 1.0
- **Score**: 100 (Green) ✓

### Scenario 2: Bridge Starting to Degrade

- Same baseline
- New trip: frequency = 2.49 Hz (1.5σ shift), variance increases 40%
- z_freq = 1.5, delta_sigma = 1.4
- **Score**: 64 (Yellow) ⚠️
- **Action**: Schedule inspection, increase monitoring frequency

### Scenario 3: Bridge in Critical Condition

- Same baseline
- New trip: frequency = 2.59 Hz (2.5σ shift), variance doubles
- z_freq = 2.5, delta_sigma = 2.2
- **Score**: 16 (Red) 🚨
- **Action**: Immediate inspection, possible traffic restrictions

---

## What Comes Next

1. **App Edge Logic** — React Native code for geofencing + accelerometer
2. **Dashboard** — Mapbox visualization with health pins
3. **Pilot Deployment** — Pick 3–5 bridges in a city, validate algorithm

The architecture is now **complete**:
- ✓ Architecture Diagram (Layer overview)
- ✓ Backend Skeleton (Signal processing + API)
- ✓ **Health Scoring Algorithm** (You are here)
- ⏳ App Edge Logic (Next)
- ⏳ Dashboard (Then)

Ready to move forward?
