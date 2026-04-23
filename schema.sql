-- Social SHM Database Schema
-- PostgreSQL 12+

-- Bridges table: Static reference data
CREATE TABLE IF NOT EXISTS bridges (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(256) NOT NULL,
  latitude DECIMAL(10, 8) NOT NULL,
  longitude DECIMAL(11, 8) NOT NULL,
  osm_id VARCHAR(64),
  country VARCHAR(2),
  region VARCHAR(128),
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_bridges_location ON bridges(latitude, longitude);
CREATE INDEX idx_bridges_osm_id ON bridges(osm_id);

-- Trips table: Raw accelerometer + GPS data per crossing
CREATE TABLE IF NOT EXISTS trips (
  id UUID PRIMARY KEY,
  bridge_id UUID NOT NULL REFERENCES bridges(id) ON DELETE CASCADE,
  trip_date TIMESTAMP NOT NULL,
  
  -- Signal processing results
  dominant_frequency DECIMAL(8, 4),  -- Hz
  frequency_confidence DECIMAL(5, 4),  -- 0..1
  peak_variance DECIMAL(8, 4),  -- Hz²
  
  -- Metadata
  median_speed DECIMAL(6, 2),  -- km/h
  trip_duration_seconds INT,
  
  -- Raw & processed data
  trip_data JSONB,  -- Peak detection results: [{ freq, power, prominence }, ...]
  metadata JSONB,  -- Device model, OS, app version, etc.
  
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_trips_bridge_date ON trips(bridge_id, trip_date DESC);
CREATE INDEX idx_trips_frequency ON trips(dominant_frequency);

-- Bridge Health Summary: Aggregated scores + baseline
CREATE TABLE IF NOT EXISTS bridge_health (
  bridge_id UUID PRIMARY KEY REFERENCES bridges(id) ON DELETE CASCADE,
  
  -- Current health status
  score INT,  -- 0..100: Green ≥70, Yellow 30-70, Red <30
  health_status VARCHAR(16),  -- 'Green', 'Yellow', 'Red', 'Unknown'
  
  -- Baseline statistics (from first 30-50 valid trips)
  baseline_frequency DECIMAL(8, 4),  -- Hz
  baseline_frequency_std DECIMAL(8, 4),
  baseline_variance DECIMAL(8, 4),
  
  -- Tracking
  trip_count INT DEFAULT 0,
  baseline_ready BOOLEAN DEFAULT FALSE,
  
  last_computed TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- Trip Audit: Track rejected/accepted decisions
CREATE TABLE IF NOT EXISTS trip_audit (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  trip_id UUID,
  bridge_id UUID,
  status VARCHAR(32),  -- 'accepted', 'rejected_outlier', 'rejected_jerk', etc.
  reason TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_audit_trip ON trip_audit(trip_id);
CREATE INDEX idx_audit_bridge_date ON trip_audit(bridge_id, created_at DESC);

-- Frequency Analysis Snapshot: Time-series of modal frequencies per bridge
CREATE TABLE IF NOT EXISTS frequency_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  bridge_id UUID NOT NULL REFERENCES bridges(id) ON DELETE CASCADE,
  
  measured_frequency DECIMAL(8, 4),  -- Hz
  frequency_std DECIMAL(8, 4),  -- Standard deviation from trips
  peak_count INT,  -- How many distinct peaks detected
  
  measurement_date TIMESTAMP NOT NULL,
  trip_count INT,  -- Number of valid trips in this window
  
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_frequency_history_bridge_date ON frequency_history(bridge_id, measurement_date DESC);

-- Dashboard Access Log (for analytics)
CREATE TABLE IF NOT EXISTS dashboard_access (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id VARCHAR(256),
  bridge_id UUID,
  action VARCHAR(64),  -- 'view_health', 'view_history', 'export'
  accessed_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_dashboard_access_date ON dashboard_access(accessed_at DESC);

-- ============================================================================
-- VIEWS: Pre-computed aggregates for faster dashboard queries
-- ============================================================================

-- Current health status across all bridges
CREATE OR REPLACE VIEW v_bridge_health_summary AS
SELECT 
  b.id,
  b.name,
  b.latitude,
  b.longitude,
  h.score,
  h.health_status,
  h.trip_count,
  h.baseline_frequency,
  h.last_computed,
  CASE 
    WHEN h.health_status = 'Red' THEN 1
    WHEN h.health_status = 'Yellow' THEN 2
    WHEN h.health_status = 'Green' THEN 3
    ELSE 4
  END as severity_rank
FROM bridges b
LEFT JOIN bridge_health h ON b.id = h.bridge_id
ORDER BY severity_rank, h.last_computed DESC NULLS LAST;

-- Frequency trend over time (last 30 days, by week)
CREATE OR REPLACE VIEW v_frequency_trend AS
SELECT
  bridge_id,
  DATE_TRUNC('week', measurement_date) as week,
  AVG(measured_frequency) as avg_frequency,
  STDDEV(measured_frequency) as std_frequency,
  COUNT(*) as measurement_count
FROM frequency_history
WHERE measurement_date > NOW() - INTERVAL '30 days'
GROUP BY bridge_id, DATE_TRUNC('week', measurement_date)
ORDER BY bridge_id, week DESC;

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Update baseline when threshold (30 trips) is reached
CREATE OR REPLACE FUNCTION update_bridge_baseline(p_bridge_id UUID)
RETURNS void AS $$
DECLARE
  v_mean_freq DECIMAL;
  v_std_freq DECIMAL;
  v_mean_var DECIMAL;
  v_count INT;
BEGIN
  SELECT 
    COUNT(*), 
    AVG(dominant_frequency),
    STDDEV(dominant_frequency),
    AVG(peak_variance)
  INTO v_count, v_mean_freq, v_std_freq, v_mean_var
  FROM trips
  WHERE bridge_id = p_bridge_id 
    AND dominant_frequency IS NOT NULL
    AND trip_date > NOW() - INTERVAL '30 days';
  
  IF v_count >= 30 THEN
    UPDATE bridge_health
    SET 
      baseline_frequency = v_mean_freq,
      baseline_frequency_std = v_std_freq,
      baseline_variance = v_mean_var,
      baseline_ready = TRUE
    WHERE bridge_id = p_bridge_id;
  END IF;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-update baseline when new trips arrive
CREATE OR REPLACE FUNCTION trigger_baseline_update()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.dominant_frequency IS NOT NULL THEN
    PERFORM update_bridge_baseline(NEW.bridge_id);
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_trip_baseline_update
AFTER INSERT ON trips
FOR EACH ROW
EXECUTE FUNCTION trigger_baseline_update();

-- ============================================================================
-- INITIAL DATA (sample bridges from OpenStreetMap)
-- ============================================================================

INSERT INTO bridges (name, latitude, longitude, osm_id, country, region) VALUES
('Golden Gate Bridge', 37.8199, -122.4783, '1234567', 'US', 'California'),
('Brooklyn Bridge', 40.7061, -73.9969, '2345678', 'US', 'New York'),
('Tower Bridge', 51.5055, -0.0754, '3456789', 'UK', 'England'),
('Sydney Harbour Bridge', -33.8568, 151.2093, '4567890', 'AU', 'New South Wales')
ON CONFLICT DO NOTHING;
