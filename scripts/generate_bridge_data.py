import json
import math
import random
import uuid
from datetime import datetime, timedelta, timezone

def generate_trip_data(health_status='healthy', duration_sec=10, sampling_rate=100):
    """
    Generates synthetic accelerometer data for a bridge crossing.
    
    health_status: 'healthy' (2.5 Hz) or 'damaged' (2.1 Hz)
    duration_sec: How long the car takes to cross
    sampling_rate: 100 Hz (100 samples per second)
    """
    
    # Core bridge frequency
    if health_status == 'healthy':
        bridge_freq = 2.5  # 2.5 cycles per second
        noise_level = 0.2
    else:
        bridge_freq = 2.1  # Slower frequency = less stiff = damaged
        noise_level = 0.5  # More noise/variance in damaged bridges
        
    num_samples = duration_sec * sampling_rate
    start_time = datetime.now(timezone.utc)
    
    accel_data = []
    gps_path = []
    
    for i in range(num_samples):
        t = i / sampling_rate
        timestamp = (start_time + timedelta(seconds=t)).isoformat().replace('+00:00', 'Z')
        
        # 1. Simulate the Bridge Wave (Sine wave)
        # Formula: sin(2 * pi * frequency * time)
        bridge_wave = math.sin(2 * math.pi * bridge_freq * t)
        
        # 2. Simulate Car Engine/Road Noise
        noise = (random.random() - 0.5) * noise_level
        
        # 3. Simulate Gravity (Z-axis is usually ~ -9.8)
        z_value = -9.81 + (bridge_wave * 0.5) + noise
        
        accel_data.append({
            "x": (random.random() - 0.5) * 0.1,
            "y": (random.random() - 0.5) * 0.1,
            "z": round(z_value, 4),
            "timestamp": timestamp
        })
        
        # Simulating GPS movement every second
        if i % sampling_rate == 0:
            gps_path.append({
                "lat": 37.8199 + (i * 0.00001),
                "lng": -122.4783 + (i * 0.00001),
                "speed_kmh": 45 + random.randint(-2, 2),
                "timestamp": timestamp
            })

    payload = {
        "bridgeId": "00000000-0000-0000-0000-000000000001", # Sample Golden Gate ID
        "tripId": str(uuid.uuid4()),
        "timestamp": start_time.isoformat().replace('+00:00', 'Z'),
        "gpsPath": gps_path,
        "accelerometerData": accel_data,
        "metadata": {
            "deviceModel": "Simulation-Tool-V1",
            "osVersion": "Python-3.x",
            "appVersion": "1.0.0-dev"
        }
    }
    
    filename = f"scripts/trip_{health_status}_{payload['tripId'][:8]}.json"
    with open(filename, 'w') as f:
        json.dump(payload, f, indent=2)
    
    print(f"Generated {health_status} trip data: {filename}")
    return filename

if __name__ == "__main__":
    # Generate one healthy and one damaged trip for testing
    generate_trip_data('healthy')
    generate_trip_data('damaged')
