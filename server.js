const express = require('express');
const pg = require('pg');
const { v4: uuidv4 } = require('uuid');
require('dotenv').config();

const app = express();
app.use(express.json({ limit: '50mb' }));

// Database connection
const pool = new pg.Pool({
  connectionString: process.env.DATABASE_URL || 'postgresql://localhost/social_shm'
});

// ============================================================================
// SIGNAL PROCESSING UTILITIES
// ============================================================================

/**
 * Compute FFT Power Spectral Density (PSD)
 * Input: array of accelerometer values
 * Output: { frequencies: [f1, f2, ...], powers: [p1, p2, ...] }
 * 
 * For now, a stub using simple DFT. In production, use fft.js or numpy equivalent.
 */
function computeFFT(samples, samplingRate = 100) {
  const n = samples.length;
  const nyquist = samplingRate / 2;
  const freqResolution = samplingRate / n;
  
  // Simple power spectrum: compute energy at each frequency bin
  // In production, use proper FFT library
  const fft = performDFT(samples);
  
  const powers = fft.map((val, i) => {
    const magnitude = Math.sqrt(val.real ** 2 + val.imag ** 2);
    return magnitude ** 2;
  });
  
  // Return only up to Nyquist frequency
  const binCount = Math.floor(n / 2);
  const frequencies = Array.from({ length: binCount }, (_, i) => i * freqResolution);
  const powerSlice = powers.slice(0, binCount);
  
  return { frequencies, powers: powerSlice, resolution: freqResolution };
}

/**
 * Naive DFT (replace with FFT.js in production)
 */
function performDFT(samples) {
  const n = samples.length;
  const result = [];
  
  for (let k = 0; k < n; k++) {
    let real = 0, imag = 0;
    for (let t = 0; t < n; t++) {
      const angle = -2 * Math.PI * k * t / n;
      real += samples[t] * Math.cos(angle);
      imag += samples[t] * Math.sin(angle);
    }
    result.push({ real, imag });
  }
  return result;
}

/**
 * Inverse Filtering: Subtract road vibration FFT from bridge FFT
 * Input: bridgeAccel (array), roadAccel (array), speed (km/h)
 * Output: filtered acceleration array
 */
function inverseFilter(bridgeAccel, roadAccel, speed) {
  // Match speeds: if road was recorded at different speed, rescale frequency bins
  // For simplicity: direct subtraction (production version uses speed-dependent scaling)
  
  const bridgeFFT = computeFFT(bridgeAccel);
  const roadFFT = computeFFT(roadAccel);
  
  // Align power spectra and subtract
  const filteredPowers = bridgeFFT.powers.map((p, i) => {
    const roadPower = roadFFT.powers[i] || 0;
    return Math.max(p - roadPower, 0); // Floor at 0
  });
  
  return { frequencies: bridgeFFT.frequencies, powers: filteredPowers };
}

/**
 * Peak Detection in Power Spectral Density
 * Returns array of detected peaks: [{ freq, power, prominence }, ...]
 * 
 * Peaks are natural frequencies of the bridge (0.5 Hz to 20 Hz range typically)
 */
function detectPeaks(frequencies, powers, minFreq = 0.5, maxFreq = 20) {
  const peaks = [];
  
  // Find indices within frequency range
  const minIdx = frequencies.findIndex(f => f >= minFreq);
  const maxIdx = frequencies.findIndex(f => f > maxFreq);
  const searchRange = frequencies.slice(minIdx, maxIdx);
  
  // Simple peak detection: local maxima with smoothing window
  const windowSize = 3;
  for (let i = windowSize; i < searchRange.length - windowSize; i++) {
    const center = powers[minIdx + i];
    const neighbors = powers.slice(minIdx + i - windowSize, minIdx + i + windowSize + 1);
    
    const isLocalMax = neighbors.every((p, idx) => idx === windowSize ? true : p <= center);
    
    if (isLocalMax && center > 0.1) { // Threshold for noise
      // Compute prominence (peak height above local baseline)
      const baseline = (neighbors[0] + neighbors[neighbors.length - 1]) / 2;
      const prominence = center - baseline;
      
      if (prominence > 0.05) {
        peaks.push({
          freq: frequencies[minIdx + i],
          power: center,
          prominence
        });
      }
    }
  }
  
  return peaks.sort((a, b) => b.power - a.power).slice(0, 3); // Top 3 modes
}

/**
 * Extract dominant frequency from peaks
 * Returns: { frequency: Hz, confidence: 0..1 }
 */
function extractDominantFrequency(peaks) {
  if (peaks.length === 0) return { frequency: null, confidence: 0 };
  
  const dominant = peaks[0];
  const totalPower = peaks.reduce((sum, p) => sum + p.power, 0);
  const confidence = dominant.power / totalPower;
  
  return { frequency: dominant.freq, confidence: Math.min(confidence, 1) };
}

/**
 * Energy-based jerk detection (high-frequency spike)
 * Returns: { rmsAccel: m/s², jerkScore: 0..1, isOutlier: bool }
 */
function detectJerk(samples, windowMs = 1000, samplingRate = 100) {
  const windowSamples = Math.floor((windowMs / 1000) * samplingRate);
  const windows = [];
  
  for (let i = 0; i < samples.length; i += windowSamples) {
    const window = samples.slice(i, i + windowSamples);
    const rms = Math.sqrt(window.reduce((sum, x) => sum + x ** 2, 0) / window.length);
    windows.push(rms);
  }
  
  const meanRMS = windows.reduce((a, b) => a + b) / windows.length;
  const stdRMS = Math.sqrt(windows.reduce((sum, x) => sum + (x - meanRMS) ** 2, 0) / windows.length);
  
  // Detect if any window is 5σ above mean (anomaly threshold)
  const maxWindow = Math.max(...windows);
  const zScore = (maxWindow - meanRMS) / (stdRMS || 1);
  
  return {
    rmsAccel: meanRMS,
    jerkScore: Math.min(zScore / 5, 1), // Normalized to [0, 1]
    isOutlier: zScore > 5
  };
}

/**
 * Health Score Computation
 * Compares current trip frequency + variance vs. baseline
 * Returns: { score: 0..100, health: 'Green'|'Yellow'|'Red', details: {...} }
 */
function computeHealthScore(currentFreq, currentVariance, baseline) {
  if (!baseline || !baseline.meanFreq) {
    return { score: null, health: 'Unknown', reason: 'Insufficient baseline data' };
  }
  
  const freqShift = Math.abs(currentFreq - baseline.meanFreq);
  const freqStd = baseline.stdFreq || 0.1;
  const varianceIncrease = currentVariance / (baseline.meanVariance || 0.5);
  
  // Scoring logic:
  // - Frequency shift of 1σ → yellow
  // - Frequency shift of 2σ + variance increase → red
  // - Variance alone > 2x → yellow
  
  let score = 100;
  let health = 'Green';
  const details = { freqShift, freqStd, varianceIncrease };
  
  if (freqShift > 2 * freqStd && varianceIncrease > 1.5) {
    score = 25;
    health = 'Red';
    details.reason = 'Frequency shift + increased instability (structural stiffness loss)';
  } else if (freqShift > freqStd || varianceIncrease > 2) {
    score = 50;
    health = 'Yellow';
    details.reason = 'Moderate frequency shift or variance increase (monitor)';
  }
  
  return { score, health, details };
}

// ============================================================================
// API ENDPOINTS
// ============================================================================

/**
 * POST /api/trips/upload
 * Ingest a single trip: accelerometer data + GPS data
 * 
 * Body: {
 *   bridgeId: "uuid",
 *   tripId: "uuid",
 *   timestamp: ISO8601,
 *   gpsPath: [{ lat, lng, speed_kmh, timestamp }, ...],
 *   accelerometerData: [{ x, y, z, timestamp }, ...],
 *   metadata: { deviceModel, osVersion, app_version }
 * }
 */
app.post('/api/trips/upload', async (req, res) => {
  const client = await pool.connect();
  
  try {
    const { bridgeId, tripId, timestamp, gpsPath, accelerometerData, metadata } = req.body;
    
    // Validate input
    if (!bridgeId || !tripId || !accelerometerData || accelerometerData.length < 100) {
      return res.status(400).json({ error: 'Invalid trip data' });
    }
    
    // Extract acceleration along vertical axis (Z)
    const verticalAccel = accelerometerData.map(a => a.z);
    
    // Compute jerk to detect outliers (potholes, etc.)
    const jerk = detectJerk(verticalAccel);
    if (jerk.isOutlier) {
      await client.query('INSERT INTO trip_audit (trip_id, status) VALUES ($1, $2)', 
        [tripId, 'rejected_outlier']);
      return res.status(202).json({ status: 'rejected', reason: 'High jerk detected' });
    }
    
    // Extract speed from GPS (use median to reduce noise)
    const speeds = gpsPath.map(p => p.speed_kmh).sort((a, b) => a - b);
    const medianSpeed = speeds[Math.floor(speeds.length / 2)];
    
    // For now, skip inverse filtering (would need road baseline from DB)
    // In production: load last 10s of road FFT before bridge, subtract it
    const bridgeFFT = computeFFT(verticalAccel);
    const peaks = detectPeaks(bridgeFFT.frequencies, bridgeFFT.powers);
    const { frequency: dominantFreq, confidence: freqConfidence } = extractDominantFrequency(peaks);
    
    // Compute variance in peak detection (how stable was the signal)
    const peakVariance = peaks.length > 1 
      ? peaks.slice(0, 2).reduce((sum, p) => sum + (p.freq - dominantFreq) ** 2, 0) / 2
      : 0;
    
    // Store trip and analysis in DB
    await client.query('BEGIN');
    
    const tripInsert = await client.query(
      `INSERT INTO trips (id, bridge_id, trip_date, dominant_frequency, frequency_confidence, 
                          peak_variance, median_speed, trip_data, metadata)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
       RETURNING id`,
      [tripId, bridgeId, new Date(timestamp), dominantFreq, freqConfidence, peakVariance, 
       medianSpeed, JSON.stringify(peaks), JSON.stringify(metadata)]
    );
    
    // Update or create bridge baseline
    const bridgeStats = await client.query(
      `SELECT COUNT(*) as count, AVG(dominant_frequency) as mean_freq, 
              STDDEV(dominant_frequency) as std_freq, AVG(peak_variance) as mean_variance
       FROM trips WHERE bridge_id = $1 AND dominant_frequency IS NOT NULL`,
      [bridgeId]
    );
    
    const stats = bridgeStats.rows[0];
    const validTrips = parseInt(stats.count);
    
    if (validTrips >= 30) {
      // Baseline is stable, compute health score
      const currentScore = computeHealthScore(
        dominantFreq,
        peakVariance,
        {
          meanFreq: parseFloat(stats.mean_freq),
          stdFreq: parseFloat(stats.std_freq),
          meanVariance: parseFloat(stats.mean_variance)
        }
      );
      
      // Store health score
      await client.query(
        `INSERT INTO bridge_health (bridge_id, score, health_status, trip_count, last_computed)
         VALUES ($1, $2, $3, $4, NOW())
         ON CONFLICT (bridge_id) DO UPDATE SET 
           score = $2, health_status = $3, trip_count = $4, last_computed = NOW()`,
        [bridgeId, currentScore.score, currentScore.health, validTrips]
      );
    } else {
      // Still learning baseline
      await client.query(
        `INSERT INTO bridge_health (bridge_id, trip_count, last_computed)
         VALUES ($1, $2, NOW())
         ON CONFLICT (bridge_id) DO UPDATE SET trip_count = $2, last_computed = NOW()`,
        [bridgeId, validTrips]
      );
    }
    
    await client.query('COMMIT');
    
    res.status(201).json({
      status: 'accepted',
      tripId,
      analysis: {
        dominantFrequency: dominantFreq,
        confidence: freqConfidence,
        peaks: peaks.length,
        jerk: jerk.rmsAccel
      }
    });
    
  } catch (err) {
    await client.query('ROLLBACK');
    console.error('Trip upload error:', err);
    res.status(500).json({ error: 'Processing failed', message: err.message });
  } finally {
    client.release();
  }
});

/**
 * GET /api/bridges/:id/health
 * Return bridge health status, frequency history, confidence
 */
app.get('/api/bridges/:id/health', async (req, res) => {
  try {
    const { id } = req.params;
    
    const health = await pool.query(
      `SELECT * FROM bridge_health WHERE bridge_id = $1`,
      [id]
    );
    
    const recentTrips = await pool.query(
      `SELECT trip_date, dominant_frequency, frequency_confidence, peak_variance
       FROM trips WHERE bridge_id = $1 ORDER BY trip_date DESC LIMIT 20`,
      [id]
    );
    
    if (health.rows.length === 0) {
      return res.status(404).json({ error: 'Bridge not found' });
    }
    
    const h = health.rows[0];
    res.json({
      bridgeId: id,
      health: h.health_status || 'Unknown',
      score: h.score,
      tripCount: h.trip_count,
      lastComputed: h.last_computed,
      recentTrips: recentTrips.rows
    });
    
  } catch (err) {
    console.error('Health query error:', err);
    res.status(500).json({ error: 'Query failed' });
  }
});

/**
 * GET /api/bridges
 * Return all bridges with health status (for dashboard)
 */
app.get('/api/bridges', async (req, res) => {
  try {
    const bridges = await pool.query(
      `SELECT b.id, b.name, b.latitude, b.longitude, h.health_status, h.score, h.trip_count
       FROM bridges b
       LEFT JOIN bridge_health h ON b.id = h.bridge_id
       ORDER BY h.score ASC NULLS LAST`
    );
    
    res.json(bridges.rows);
  } catch (err) {
    console.error('Bridges query error:', err);
    res.status(500).json({ error: 'Query failed' });
  }
});

/**
 * POST /api/bridges
 * Register a new bridge (admin)
 */
app.post('/api/bridges', async (req, res) => {
  try {
    const { name, latitude, longitude, openStreetMapId } = req.body;
    
    const result = await pool.query(
      `INSERT INTO bridges (name, latitude, longitude, osm_id)
       VALUES ($1, $2, $3, $4)
       RETURNING id`,
      [name, latitude, longitude, openStreetMapId]
    );
    
    res.status(201).json({ bridgeId: result.rows[0].id });
  } catch (err) {
    console.error('Bridge create error:', err);
    res.status(500).json({ error: 'Creation failed' });
  }
});

/**
 * GET /api/health/status
 * Liveness check
 */
app.get('/api/health/status', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date() });
});

// ============================================================================
// ERROR HANDLING & SERVER START
// ============================================================================

app.use((err, req, res, next) => {
  console.error(err);
  res.status(500).json({ error: 'Internal server error' });
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Social SHM backend listening on port ${PORT}`);
});

module.exports = app;
