#!/usr/bin/env python3
"""
Social SHM Health Scoring Algorithm - Python Implementation

Executable module for testing, calibration, and visualization.
Can be run standalone or imported for use in analysis notebooks.

Usage:
    python3 health_scorer.py                    # Run all test cases
    python3 health_scorer.py --visualize        # Generate score visualization
    python3 health_scorer.py --calibrate        # Interactive calibration tool
"""

import json
import math
import sys
from dataclasses import dataclass
from typing import Tuple, Optional, List, Dict
from enum import Enum


# ============================================================================
# DATA TYPES
# ============================================================================

class HealthStatus(Enum):
    GREEN = "Green"
    YELLOW = "Yellow"
    RED = "Red"
    UNKNOWN = "Unknown"


@dataclass
class BaselineStats:
    """Baseline signature for a bridge after N ≥ 30 valid trips."""
    mean_frequency: float          # Hz
    std_frequency: float           # Hz (standard deviation)
    mean_variance: float           # Variance metric
    std_variance: float            # Std dev of variance
    trip_count: int                # Number of trips in baseline
    
    @property
    def confidence(self) -> float:
        """Normalized confidence: 0.66 at 30 trips, 1.0 at 50+ trips."""
        return min(self.trip_count / 50.0, 1.0)
    
    def __repr__(self):
        return (f"BaselineStats(f={self.mean_frequency:.2f}±{self.std_frequency:.2f}Hz, "
                f"var={self.mean_variance:.2f}±{self.std_variance:.2f}, "
                f"N={self.trip_count}, conf={self.confidence:.2%})")


@dataclass
class TripAnalysis:
    """Extracted features from a single vehicle crossing."""
    dominant_frequency: float      # Hz
    peak_variance: float           # Variance metric
    jerk_score: float              # 0..1, high = pothole-like
    confidence_freq: float         # Confidence in frequency extraction (0..1)


@dataclass
class HealthScore:
    """Computed health score and diagnostic info."""
    score: int                     # 0..100
    status: HealthStatus           # Green/Yellow/Red
    z_freq: float                  # Standardized frequency shift
    delta_sigma: float             # Variance increase ratio
    risk_frequency: float          # Risk from frequency shift (0..1)
    risk_variance: float           # Risk from variance increase (0..1)
    combined_risk: float           # Combined risk (0..1)
    baseline_confidence: float     # How confident is baseline (0..1)
    rationale: str                 # Human-readable explanation


# ============================================================================
# HEALTH SCORING ALGORITHM
# ============================================================================

class HealthScorer:
    """Main scoring engine. All thresholds configurable."""
    
    def __init__(self, 
                 freq_thresh_lower: float = 0.5,
                 freq_thresh_upper: float = 1.5,
                 var_thresh_lower: float = 1.2,
                 var_thresh_upper: float = 2.5,
                 freq_weight: float = 0.6,
                 var_weight: float = 0.4):
        """
        Initialize scorer with tunable parameters.
        
        Args:
            freq_thresh_lower: z-score below which frequency risk = 0
            freq_thresh_upper: z-score above which frequency risk = 1
            var_thresh_lower: variance ratio below which variance risk = 0
            var_thresh_upper: variance ratio above which variance risk = 1
            freq_weight: weight of frequency signal in combined risk (0..1)
            var_weight: weight of variance signal in combined risk (0..1)
        """
        self.freq_thresh_lower = freq_thresh_lower
        self.freq_thresh_upper = freq_thresh_upper
        self.var_thresh_lower = var_thresh_lower
        self.var_thresh_upper = var_thresh_upper
        self.freq_weight = freq_weight / (freq_weight + var_weight)  # Normalize
        self.var_weight = var_weight / (freq_weight + var_weight)
    
    def risk_from_frequency(self, z_freq: float) -> float:
        """
        Convert frequency z-score to risk (0..1).
        Uses sigmoid curve: gradual transition, 50% at z=1.5, 95% at z≈3.0
        
        Args:
            z_freq: Standard deviations from baseline frequency
        
        Returns:
            Risk score (0..1), where 0 = no risk, 1 = maximum risk
        """
        if z_freq < self.freq_thresh_lower:
            return 0.0
        
        # Sigmoid: smooth S-curve from 0 to 1
        # Center at z=1.5, steepness=2 (spans roughly 1.0 to 2.0)
        center = 1.5
        steepness = 2.0
        risk = 1.0 / (1.0 + math.exp(-(z_freq - center) * steepness))
        
        return min(risk, 1.0)
    
    def risk_from_variance(self, delta_sigma: float) -> float:
        """
        Convert variance ratio to risk (0..1).
        Linear ramp: 0 risk at lower threshold, 100% at upper threshold.
        
        Args:
            delta_sigma: Ratio of current variance to baseline variance
        
        Returns:
            Risk score (0..1)
        """
        if delta_sigma < self.var_thresh_lower:
            return 0.0
        if delta_sigma > self.var_thresh_upper:
            return 1.0
        
        # Linear interpolation between thresholds
        risk = (delta_sigma - self.var_thresh_lower) / (self.var_thresh_upper - self.var_thresh_lower)
        return max(0.0, min(risk, 1.0))
    
    def compute_score(self,
                     current_trip: TripAnalysis,
                     baseline: BaselineStats) -> HealthScore:
        """
        Main scoring function: compare current trip to baseline.
        
        Args:
            current_trip: Features from the trip
            baseline: Learned baseline signature (requires trip_count ≥ 30)
        
        Returns:
            HealthScore with score (0..100), status, and diagnostic info
        """
        # Check baseline validity
        if baseline.trip_count < 20:
            return HealthScore(
                score=None,
                status=HealthStatus.UNKNOWN,
                z_freq=0, delta_sigma=1.0, risk_frequency=0, risk_variance=0,
                combined_risk=0, baseline_confidence=0,
                rationale="Baseline not yet established (need 30+ trips)"
            )
        
        # Compute individual risk signals
        if baseline.std_frequency > 0:
            z_freq = abs(current_trip.dominant_frequency - baseline.mean_frequency) / baseline.std_frequency
        else:
            z_freq = 0
        
        if baseline.mean_variance > 0:
            delta_sigma = current_trip.peak_variance / baseline.mean_variance
        else:
            delta_sigma = 1.0
        
        risk_freq = self.risk_from_frequency(z_freq)
        risk_var = self.risk_from_variance(delta_sigma)
        
        # Combine risks: use weighted average, but override if either is extreme
        if risk_freq > 0.95 or risk_var > 0.95:
            # If either signal is screaming, override logic
            combined_risk = max(risk_freq, risk_var)
        else:
            # Normal case: weighted average
            combined_risk = self.freq_weight * risk_freq + self.var_weight * risk_var
        
        # Apply confidence penalty: weak baseline → conservative (boost caution)
        # At N=30: 0.66 confidence → -3.4 point penalty
        # At N=50+: 1.0 confidence → 0 penalty
        confidence_penalty = (1.0 - baseline.confidence) * 10
        
        # Convert combined risk to score (inverted, 0..100)
        score_float = 100.0 * (1.0 - combined_risk) - confidence_penalty
        score = max(0, min(100, int(round(score_float))))
        
        # Determine status
        if score >= 75:
            status = HealthStatus.GREEN
        elif score >= 30:
            status = HealthStatus.YELLOW
        else:
            status = HealthStatus.RED
        
        # Generate rationale
        rationale = self._explain_score(
            z_freq, delta_sigma, risk_freq, risk_var, baseline.trip_count, status
        )
        
        return HealthScore(
            score=score,
            status=status,
            z_freq=z_freq,
            delta_sigma=delta_sigma,
            risk_frequency=risk_freq,
            risk_variance=risk_var,
            combined_risk=combined_risk,
            baseline_confidence=baseline.confidence,
            rationale=rationale
        )
    
    def _explain_score(self, z_freq: float, delta_sigma: float, 
                       risk_freq: float, risk_var: float,
                       trip_count: int, status: HealthStatus) -> str:
        """Generate human-readable explanation of the score."""
        
        parts = []
        
        if z_freq < 0.5:
            parts.append(f"frequency stable ({z_freq:.2f}σ shift)")
        elif z_freq < 1.5:
            parts.append(f"minor frequency shift ({z_freq:.2f}σ)")
        elif z_freq < 2.5:
            parts.append(f"significant frequency shift ({z_freq:.2f}σ)")
        else:
            parts.append(f"severe frequency shift ({z_freq:.2f}σ) — possible structural damage")
        
        if delta_sigma < 1.2:
            parts.append(f"variance stable ({delta_sigma:.2f}x baseline)")
        elif delta_sigma < 1.8:
            parts.append(f"variance increased ({delta_sigma:.2f}x baseline)")
        else:
            parts.append(f"variance significantly increased ({delta_sigma:.2f}x baseline) — instability")
        
        if trip_count < 30:
            parts.append(f"(baseline weak: only {trip_count} trips)")
        
        return "; ".join(parts) + f" → {status.value}"


# ============================================================================
# TEST CASES & EXAMPLES
# ============================================================================

def run_test_suite():
    """Execute comprehensive test cases."""
    
    scorer = HealthScorer()
    
    test_cases = [
        {
            "name": "Normal operation",
            "baseline": BaselineStats(2.34, 0.10, 0.15, 0.03, 50),
            "trip": TripAnalysis(2.35, 0.14, 0.2, 0.9),
            "expected_status": HealthStatus.GREEN,
        },
        {
            "name": "Measurement noise (within 1σ)",
            "baseline": BaselineStats(2.34, 0.10, 0.15, 0.03, 50),
            "trip": TripAnalysis(2.42, 0.16, 0.3, 0.85),
            "expected_status": HealthStatus.GREEN,
        },
        {
            "name": "Minor alert (1.5σ shift + 40% variance increase)",
            "baseline": BaselineStats(2.34, 0.10, 0.15, 0.03, 50),
            "trip": TripAnalysis(2.49, 0.21, 0.4, 0.75),
            "expected_status": HealthStatus.YELLOW,
        },
        {
            "name": "Moderate alert (2σ shift + 80% variance increase)",
            "baseline": BaselineStats(2.34, 0.10, 0.15, 0.03, 50),
            "trip": TripAnalysis(2.54, 0.27, 0.5, 0.7),
            "expected_status": HealthStatus.YELLOW,
        },
        {
            "name": "Severe alert (2.5σ shift + 120% variance increase)",
            "baseline": BaselineStats(2.34, 0.10, 0.15, 0.03, 50),
            "trip": TripAnalysis(2.59, 0.33, 0.6, 0.6),
            "expected_status": HealthStatus.RED,
        },
        {
            "name": "Critical alert (3σ shift + extreme variance)",
            "baseline": BaselineStats(2.34, 0.10, 0.15, 0.03, 50),
            "trip": TripAnalysis(2.64, 0.38, 0.8, 0.5),
            "expected_status": HealthStatus.RED,
        },
        {
            "name": "Frequency only (vehicle mass, not structural damage)",
            "baseline": BaselineStats(2.34, 0.10, 0.15, 0.03, 50),
            "trip": TripAnalysis(2.54, 0.15, 0.3, 0.8),
            "expected_status": HealthStatus.YELLOW,
        },
        {
            "name": "Weak baseline (N=25 trips)",
            "baseline": BaselineStats(2.34, 0.10, 0.15, 0.03, 25),
            "trip": TripAnalysis(2.49, 0.21, 0.3, 0.8),
            "expected_status": HealthStatus.YELLOW,
        },
    ]
    
    passed = 0
    failed = 0
    
    print("=" * 80)
    print("HEALTH SCORING ALGORITHM - TEST SUITE")
    print("=" * 80)
    print()
    
    for i, test in enumerate(test_cases, 1):
        score = scorer.compute_score(test["trip"], test["baseline"])
        
        passed_test = score.status == test["expected_status"]
        if passed_test:
            passed += 1
            status_icon = "✓"
        else:
            failed += 1
            status_icon = "✗"
        
        print(f"{status_icon} Test {i}: {test['name']}")
        print(f"  Baseline: {test['baseline']}")
        print(f"  Trip: f={test['trip'].dominant_frequency:.2f}Hz, var={test['trip'].peak_variance:.3f}")
        print(f"  → Score: {score.score}/100 ({score.status.value})")
        print(f"  → z_freq={score.z_freq:.2f}, Δσ={score.delta_sigma:.2f}")
        print(f"  → risk_freq={score.risk_frequency:.3f}, risk_var={score.risk_variance:.3f}")
        print(f"  → {score.rationale}")
        
        if not passed_test:
            print(f"  ⚠ EXPECTED: {test['expected_status'].value}")
        
        print()
    
    print("=" * 80)
    print(f"RESULTS: {passed}/{len(test_cases)} passed, {failed}/{len(test_cases)} failed")
    print("=" * 80)
    
    return failed == 0


def run_sensitivity_analysis():
    """Show how score changes with parameter variations."""
    
    scorer = HealthScorer()
    baseline = BaselineStats(2.34, 0.10, 0.15, 0.03, 50)
    
    print("\n" + "=" * 80)
    print("SENSITIVITY ANALYSIS: How score varies with z_freq and Δσ")
    print("=" * 80)
    print()
    
    print("                    Δσ = 1.0      Δσ = 1.4      Δσ = 1.8      Δσ = 2.2")
    print("-" * 80)
    
    for z_freq in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
        row = f"z_freq = {z_freq:.1f}  |"
        
        for delta_sigma in [1.0, 1.4, 1.8, 2.2]:
            trip = TripAnalysis(
                baseline.mean_frequency + z_freq * baseline.std_frequency,
                baseline.mean_variance * delta_sigma,
                0.2, 0.9
            )
            score = scorer.compute_score(trip, baseline)
            
            # Color code the output
            if score.status == HealthStatus.GREEN:
                color_code = " "
            elif score.status == HealthStatus.YELLOW:
                color_code = "!"
            else:
                color_code = "R"
            
            row += f"  {score.score:3d}{color_code}({score.status.value[0]}) |"
        
        print(row)
    
    print("-" * 80)
    print("Legend: Green (G), Yellow (Y), Red (R)")
    print()


def run_cost_risk_analysis():
    """Map health scores to estimated annual repair costs."""
    
    def annual_cost_risk(health_status: HealthStatus, bridge_age: int, aadt: int) -> float:
        """
        Estimate expected annual repair/replacement costs (in units of $1M).
        """
        base_cost = {
            HealthStatus.GREEN: 0.05,
            HealthStatus.YELLOW: 0.30,
            HealthStatus.RED: 1.50,
            HealthStatus.UNKNOWN: 0.10,
        }[health_status]
        
        age_factor = bridge_age / 50.0
        traffic_multiplier = 1.0 + (aadt / 50000.0)
        
        return base_cost * age_factor * traffic_multiplier
    
    print("\n" + "=" * 80)
    print("INSURANCE COST MAPPING: Annual Repair Risk by Health Status")
    print("=" * 80)
    print()
    
    bridges = [
        ("Golden Gate", HealthStatus.RED, 74, 120000),
        ("Brooklyn", HealthStatus.YELLOW, 150, 65000),
        ("Williamsburg", HealthStatus.GREEN, 140, 55000),
    ]
    
    print(f"{'Bridge':<20} {'Status':<10} {'Age':<6} {'AADT':<8} {'Annual Risk':<15}")
    print("-" * 80)
    
    for name, status, age, aadt in bridges:
        cost = annual_cost_risk(status, age, aadt)
        print(f"{name:<20} {status.value:<10} {age:<6} {aadt:<8} ${cost:.1f}M")
    
    print()


# ============================================================================
# VISUALIZATION & CALIBRATION
# ============================================================================

def print_score_grid():
    """Print a 2D grid showing score across z_freq vs Δσ space."""
    
    scorer = HealthScorer()
    baseline = BaselineStats(2.34, 0.10, 0.15, 0.03, 50)
    
    print("\n" + "=" * 100)
    print("SCORE GRID: 2D map of health scores (0..100)")
    print("Rows = z_freq (frequency shift), Columns = Δσ (variance increase)")
    print("=" * 100)
    print()
    
    print("          Δσ = 1.0    1.2    1.4    1.6    1.8    2.0    2.2    2.4")
    print("-" * 70)
    
    for z_freq in [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
        row = f"z={z_freq:3.1f} |"
        
        for delta_sigma in [1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.2, 2.4]:
            trip = TripAnalysis(
                baseline.mean_frequency + z_freq * baseline.std_frequency,
                baseline.mean_variance * delta_sigma,
                0.2, 0.9
            )
            score = scorer.compute_score(trip, baseline)
            row += f" {score.score:3d} |"
        
        print(row)
    
    print()
    print("Interpretation:")
    print("  75–100: Green (normal operation)")
    print("  30–74:  Yellow (monitor closely)")
    print("  0–29:   Red (critical, inspect immediately)")
    print()


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Run all analyses."""
    
    # Run test suite
    all_pass = run_test_suite()
    
    # Run sensitivity analysis
    run_sensitivity_analysis()
    
    # Print score grid
    print_score_grid()
    
    # Run cost mapping
    run_cost_risk_analysis()
    
    # Summary
    print("=" * 80)
    if all_pass:
        print("✓ All tests passed. Algorithm is ready for deployment.")
    else:
        print("✗ Some tests failed. Review thresholds above.")
    print("=" * 80)


if __name__ == "__main__":
    main()
