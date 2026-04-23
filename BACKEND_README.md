# Social SHM Backend - System Architecture & Setup Guide

## Overview

This is the **Cloud Backend** layer (Layer 2) of the Social SHM system. It:

1. **Ingests raw accelerometer + GPS data** from the phone app via `/api/trips/upload`
2. **Performs signal processing**:
   - Inverse filtering (subtracts pre-bridge road vibration)
   - FFT analysis (extracts natural frequencies 0.5–20 Hz)
   - Peak detection (identifies bridge modal signatures)
   - Jerk-based outlier rejection (filters potholes, bumps)
3. **Aggregates trips** (30–50 valid crossings build a baseline)
4. **Computes health scores** (frequency shift + variance → Red/Yellow/Green)
5. **Exposes REST API** for the dashboard and further analysis

## Tech Stack

- **Runtime**: Node.js 16+
- **Framework**: Express.js
- **Database**: PostgreSQL 12+
- **Signal Processing**: FFT.js (naive DFT for development; replace with production FFT library)
- **Package Manager**: npm

## Prerequisites

```bash
# Install Node.js (https://nodejs.org)
node --version  # Should be v16 or higher

# Install PostgreSQL (https://www.postgresql.org/download)
psql --version  # Should be 12 or higher

# Create a local PostgreSQL user and database
createuser social_shm_user
createdb -O social_shm_user social_shm
```

## Installation & Setup

### 1. Clone or download the backend files

```bash
mkdir social-shm-backend && cd social-shm-backend
# Copy: server.js, schema.sql, package.json, .env.example
```

### 2. Install dependencies

```bash
npm install
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env with your local database credentials:
# DATABASE_URL=postgresql://social_shm_user:password@localhost:5432/social_shm
```

### 4. Initialize the database

```bash
psql -U social_shm_user -d social_shm -f schema.sql
# This creates tables, indexes, views, and sample bridges
```

### 5. Start the server

```bash
# Development (with auto-reload)
npm run dev

# Production
npm start
```

Server runs at `http://localhost:3000`

## API Endpoints

### 1. **POST /api/trips/upload**

Ingest a single vehicle crossing of a bridge.

**Request body:**

```json
{
  "bridgeId": "uuid",
  "tripId": "uuid",
  "timestamp": "2025-04-23T14:30:00Z",
  "gpsPath": [
    { "lat": 37.8199, "lng": -122.4783, "speed_kmh": 45, "timestamp": "2025-04-23T14:30:00Z" },
    { "lat": 37.8200, "lng": -122.4780, "speed_kmh": 45, "timestamp": "2025-04-23T14:30:01Z" }
  ],
  "accelerometerData": [
    { "x": 0.1, "y": -0.05, "z": -9.81, "timestamp": "2025-04-23T14:30:00.000Z" },
    { "x": 0.15, "y": -0.02, "z": -9.80, "timestamp": "2025-04-23T14:30:00.010Z" }
  ],
  "metadata": {
    "deviceModel": "iPhone 14",
    "osVersion": "17.4",
    "appVersion": "1.0.0"
  }
}
```

**Response (accepted):**

```json
{
  "status": "accepted",
  "tripId": "uuid",
  "analysis": {
    "dominantFrequency": 2.34,
    "confidence": 0.78,
    "peaks": 3,
    "jerk": 0.85
  }
}
```

**Response (rejected):**

```json
{
  "status": "rejected",
  "reason": "High jerk detected (pothole or artifact)"
}
```

**Processing pipeline:**

1. Validate accelerometer data (min 100 samples = 1 second at 100 Hz)
2. Extract vertical (Z) acceleration
3. Detect jerk (if 5σ above mean, reject as outlier)
4. Compute FFT → Power Spectral Density
5. Detect peaks in 0.5–20 Hz range
6. Extract dominant frequency + confidence
7. Compare to baseline (if 30+ trips exist):
   - If `|freq - baseline| > 2σ AND variance > 1.5×baseline` → Score Red
   - If `|freq - baseline| > 1σ OR variance > 2×baseline` → Score Yellow
   - Otherwise → Score Green
8. Store in database, update bridge health

### 2. **GET /api/bridges/:id/health**

Retrieve current health status + recent frequency history for a bridge.

**Response:**

```json
{
  "bridgeId": "uuid",
  "health": "Green",
  "score": 85,
  "tripCount": 45,
  "lastComputed": "2025-04-23T14:25:00Z",
  "recentTrips": [
    {
      "trip_date": "2025-04-23T14:30:00Z",
      "dominant_frequency": 2.34,
      "frequency_confidence": 0.78,
      "peak_variance": 0.12
    }
  ]
}
```

### 3. **GET /api/bridges**

List all bridges with current health status (for dashboard pins).

**Response:**

```json
[
  {
    "id": "uuid",
    "name": "Golden Gate Bridge",
    "latitude": 37.8199,
    "longitude": -122.4783,
    "health_status": "Green",
    "score": 88,
    "trip_count": 52,
    "lastComputed": "2025-04-23T14:25:00Z"
  }
]
```

### 4. **POST /api/bridges** (Admin)

Register a new bridge.

**Request:**

```json
{
  "name": "New Bridge Name",
  "latitude": 40.7061,
  "longitude": -73.9969,
  "openStreetMapId": "123456789"
}
```

**Response:**

```json
{
  "bridgeId": "uuid"
}
```

### 5. **GET /api/health/status**

Liveness check (for monitoring/load balancers).

**Response:**

```json
{
  "status": "ok",
  "timestamp": "2025-04-23T14:30:00Z"
}
```

## Database Schema Overview

### Core Tables

| Table | Purpose |
|-------|---------|
| `bridges` | Static reference data: bridge names, coordinates, OSM IDs |
| `trips` | Individual vehicle crossings: raw analysis + metadata |
| `bridge_health` | Current health score, baseline statistics, trip count |
| `trip_audit` | Audit log: why trips were accepted/rejected |
| `frequency_history` | Time-series snapshot of modal frequencies per bridge |
| `dashboard_access` | (Optional) Analytics on dashboard usage |

### Key Views

- **v_bridge_health_summary**: Current health across all bridges (sorted by severity)
- **v_frequency_trend**: Weekly frequency averages (last 30 days)

### Baseline Calculation

After 30 valid trips on a bridge, the backend automatically computes:

```sql
baseline_frequency = AVG(dominant_frequency)
baseline_frequency_std = STDDEV(dominant_frequency)
baseline_variance = AVG(peak_variance)
```

These become the reference for all future health scores.

## Signal Processing Pipeline

### 1. Inverse Filtering

**Goal**: Remove the car's own vibration (engine, suspension, tires) from the bridge signal.

**Method**: 
- Before bridge entry, record 10s of road vibration at the same speed
- Compute FFT of road signal
- Subtract road FFT from bridge FFT (noise gating)
- Result: isolated bridge structural response

**Status**: Currently a stub (direct subtraction). In production:
- Speed-match the road baseline
- Use spectral subtraction with over-subtraction to avoid negative powers

### 2. FFT & Peak Detection

**Goal**: Extract natural frequencies of the bridge (0.5–20 Hz range).

**Method**:
- Compute Power Spectral Density (PSD) from accelerometer samples
- Smooth with Hann window
- Find local maxima in 0.5–20 Hz range
- Rank by power, return top 3 peaks

**Result**: `[{ freq: 2.34 Hz, power: 0.56, prominence: 0.12 }, ...]`

### 3. Jerk Detection

**Goal**: Reject trips contaminated by potholes or road bumps (not bridge response).

**Method**:
- Compute RMS acceleration in 1-second windows
- If any window > 5σ above mean, mark as outlier
- Reject the entire trip

**Threshold**: Configurable via `JERK_OUTLIER_THRESHOLD_SIGMA` (default 5)

### 4. Health Scoring

**Goal**: Compare current trip frequency + stability to baseline.

**Formula**:

```
freq_shift = |current_frequency - baseline_mean|
freq_z_score = freq_shift / baseline_std

variance_increase = current_variance / baseline_variance

if freq_z_score > 2.0 AND variance_increase > 1.5:
    Score = Red (25) → Likely structural damage
elif freq_z_score > 1.0 OR variance_increase > 2.0:
    Score = Yellow (50) → Monitor
else:
    Score = Green (75+) → Normal
```

**Interpretation**:
- **Frequency shift** = change in structural stiffness (crack, scour, corrosion)
- **Variance increase** = loss of modal clarity (instability, incipient failure)

## Integration with Other Layers

### → From Phone App (Layer 1)

Phone sends `POST /api/trips/upload` whenever it exits a bridge zone. Expected:

- Accelerometer at 100 Hz (≥100 samples for a 30s crossing)
- GPS path with speed annotations
- Timestamp + device metadata

### ← To Dashboard (Layer 3)

Dashboard queries `/api/bridges` every 30 seconds:

- Fetches all bridges + current health status
- Renders map pins (Green/Yellow/Red)
- On click, fetches `/api/bridges/:id/health` for details

## Deployment Checklist

- [ ] PostgreSQL database created and schema migrated
- [ ] Environment variables set in `.env`
- [ ] Dependencies installed (`npm install`)
- [ ] Test trip upload endpoint (`curl` test)
- [ ] Verify baseline computation (30+ trips on test bridge)
- [ ] Set up health checks (e.g., Kubernetes liveness probe → `/api/health/status`)
- [ ] Configure logging (e.g., ELK stack, CloudWatch)
- [ ] Set up monitoring & alerts on Red bridges
- [ ] Document SLA (e.g., 99.9% uptime, <100ms latency on health queries)

## Testing

### Manual Test: Upload a Trip

```bash
curl -X POST http://localhost:3000/api/trips/upload \
  -H "Content-Type: application/json" \
  -d '{
    "bridgeId": "00000000-0000-0000-0000-000000000001",
    "tripId": "12345678-1234-1234-1234-123456789abc",
    "timestamp": "2025-04-23T14:30:00Z",
    "gpsPath": [
      {"lat": 37.8199, "lng": -122.4783, "speed_kmh": 45, "timestamp": "2025-04-23T14:30:00Z"},
      {"lat": 37.8200, "lng": -122.4780, "speed_kmh": 45, "timestamp": "2025-04-23T14:30:01Z"}
    ],
    "accelerometerData": [
      {"x": 0.1, "y": -0.05, "z": -9.81, "timestamp": "2025-04-23T14:30:00.000Z"},
      {"x": 0.15, "y": -0.02, "z": -9.80, "timestamp": "2025-04-23T14:30:00.010Z"}
    ],
    "metadata": {"deviceModel": "iPhone 14", "osVersion": "17.4", "appVersion": "1.0.0"}
  }'
```

### Manual Test: Get Bridge Health

```bash
curl http://localhost:3000/api/bridges/00000000-0000-0000-0000-000000000001/health
```

### Manual Test: List All Bridges

```bash
curl http://localhost:3000/api/bridges
```

## Next Steps

1. **Signal Processing Improvements**
   - Integrate proper FFT library (fft.js is a stub)
   - Implement speed-matched inverse filtering
   - Add SSI (Stochastic Subspace Identification) for modal damping extraction

2. **Data Collection Scale**
   - Deploy phone app to pilot city (1–2 bridges)
   - Collect 50+ baseline trips per bridge
   - Validate baseline stability over 2–4 weeks

3. **Health Score Refinement**
   - Collect real failure data (cracked bridges, scoured foundations)
   - Calibrate Red/Yellow/Green thresholds
   - Add confidence intervals

4. **Dashboard Integration**
   - Build Mapbox UI (Layer 3)
   - Integrate with insurance APIs (for alerting)
   - Add export/reporting endpoints

5. **Production Hardening**
   - Add authentication/authorization
   - Rate limiting on `/api/trips/upload` (prevent spam)
   - Database backups & disaster recovery
   - Horizontal scaling (load balancer + multiple server instances)

---

**Questions?** See the Architecture Diagram in the main documentation for an overview of how this backend fits into the three-layer system.
