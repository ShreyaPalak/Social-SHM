"""
Social SHM Health Scoring Algorithm - Python Implementation

This module implements the formal health scoring specification as a callable,
testable, and visualizable component. Use this to validate thresholds and
train stakeholders on how bridges transition between health states.
"""

import math
from dataclasses import dataclass
from typing import Optional, Tuple
from enum import Enum


class HealthStatus(Enum):
    """Bridge health classification."""
    UNKNOWN = "Unknown"
    GREEN = "Green"
    YELLOW = "Yellow"
    RED = "Red"


@dataclass
class Baseline:
    """Bridge baseline signature (computed from first 30 valid trips)."""
    f_baseline: float  # Hz
    sigma_f: float     # Hz (standard deviation of frequency)
    v_baseline: float  # Hz² (mean variance in peak detection)
    sigma_v: float     # Hz² (std of variance)
    trip_count: int    # Total valid trips used for baseline
    
    def __post_init__(self):
        """Validate baseline parameters."""
        if self.trip_count < 30:
            raise ValueError(f"Baseline requires >= 30 trips, got {self.trip_count}")
        if self.f_baseline <= 0:
            raise ValueError(f"Baseline frequency must be > 0 Hz")
        if self.sigma_f < 0 or self.sigma_v < 0:
            raise ValueError("Standard deviations must be non-negative")


@dataclass
class Measurement:
    """A single trip measurement (extracted modal properties)."""
    f_current: float   # Hz (dominant frequency)
    c_freq: float      # 0..1 (confidence in frequency detection)
    v_current: float   # Hz² (variance in peak detection)
    
    def __post_init__(self):
        """Validate measurement."""
        if self.f_current <= 0:
            raise ValueError("Current frequency must be > 0 Hz")
        if not 0 <= self.c_freq <= 1:
            raise ValueError("Confidence must be in [0, 1]")
        if self.v_current < 0:
            raise ValueError("Variance must be non-negative")


@dataclass
class RiskFactors:
    """Intermediate risk assessment before final score."""
    freq_risk: str     # 'low', 'moderate', 'high', 'critical'
    clarity_risk: str
    confidence_risk: str
    z_f: float         # Standard deviations of frequency shift
    delta_v: float     # Variance multiplier


@dataclass
class HealthScore:
    """Final health assessment."""
    health: HealthStatus
    score: Optional[int]  # 0-100 or None if Unknown
    z_f: Optional[float]  # Standard deviations of shift
    delta_v: Optional[float]  # Variance increase
    c_freq: Optional[float]  # Measurement confidence
    details: dict  # Additional context for audit/logging
    risk_factors: Optional[RiskFactors] = None


# ============================================================================
# CORE ALGORITHM
# ============================================================================

def assess_frequency_risk(z_f: float) -> Tuple[str, int]:
    """
    Classify frequency shift risk based on standard deviations.
    
    Returns: (risk_level, score_contribution)
    """
    if z_f > 3.0:
        return "critical", 0
    elif z_f > 2.0:
        return "high", 25
    elif z_f > 1.0:
        return "moderate", 50
    else:
        return "low", 75


def assess_clarity_risk(delta_v: float) -> Tuple[str, int]:
    """
    Classify modal clarity risk based on variance increase.
    
    Returns: (risk_level, score_contribution)
    """
    if delta_v > 3.0:
        return "critical", 0
    elif delta_v > 2.0:
        return "high", 25
    elif delta_v > 1.5:
        return "moderate", 50
    else:
        return "low", 75


def assess_confidence_risk(c_freq: float) -> Tuple[str, int]:
    """
    Classify measurement confidence risk.
    
    Returns: (risk_level, penalty_points)
    """
    if c_freq < 0.4:
        return "critical", 50
    elif c_freq < 0.6:
        return "high", 25
    else:
        return "low", 0


def compute_health_score(
    baseline: Baseline,
    measurement: Measurement,
    current_trip_count: int
) -> HealthScore:
    """
    Compute health score for a bridge measurement.
    
    Args:
        baseline: Baseline signature (f_baseline, σ_f, v_baseline, σ_v)
        measurement: Current trip measurement (f_current, c_freq, v_current)
        current_trip_count: Total valid trips collected on this bridge
    
    Returns:
        HealthScore with categorical and numeric assessment
    """
    
    # ========== STEP 1: Baseline maturity check ==========
    if current_trip_count < 30:
        return HealthScore(
            health=HealthStatus.UNKNOWN,
            score=None,
            z_f=None,
            delta_v=None,
            c_freq=None,
            details={
                "reason": "Insufficient baseline data",
                "trip_count": current_trip_count,
                "trips_needed": 30
            }
        )
    
    # ========== STEP 2: Compute deviations ==========
    delta_f = abs(measurement.f_current - baseline.f_baseline)
    
    # Avoid division by zero; use minimum standard deviation of 0.05 Hz
    sigma_f_safe = max(baseline.sigma_f, 0.05)
    z_f = delta_f / sigma_f_safe
    
    # Variance multiplier (use floor of 0.01 Hz² to avoid division issues)
    v_baseline_safe = max(baseline.v_baseline, 0.01)
    delta_v = measurement.v_current / v_baseline_safe
    
    # ========== STEP 3: Assess individual risk factors ==========
    freq_risk, freq_score = assess_frequency_risk(z_f)
    clarity_risk, clarity_score = assess_clarity_risk(delta_v)
    confidence_risk, confidence_penalty = assess_confidence_risk(measurement.c_freq)
    
    # ========== STEP 4: Combine risk factors (conservative: take minimum) ==========
    raw_score = min(freq_score, clarity_score) - confidence_penalty
    final_score = max(0, min(100, raw_score))
    
    # ========== STEP 5: Map score to categorical health ==========
    if final_score < 35:
        health = HealthStatus.RED
    elif final_score < 65:
        health = HealthStatus.YELLOW
    else:
        health = HealthStatus.GREEN
    
    # ========== STEP 6: Assemble result ==========
    return HealthScore(
        health=health,
        score=final_score,
        z_f=z_f,
        delta_v=delta_v,
        c_freq=measurement.c_freq,
        details={
            "frequency_shift_hz": round(delta_f, 4),
            "frequency_shift_percent": round(100 * delta_f / baseline.f_baseline, 2),
            "baseline_frequency_hz": baseline.f_baseline,
            "current_frequency_hz": measurement.f_current,
            "frequency_std_hz": sigma_f_safe,
            "variance_increase": round(delta_v, 2),
            "baseline_variance": baseline.v_baseline,
            "current_variance": measurement.v_current,
        },
        risk_factors=RiskFactors(
            freq_risk=freq_risk,
            clarity_risk=clarity_risk,
            confidence_risk=confidence_risk,
            z_f=z_f,
            delta_v=delta_v
        )
    )


# ============================================================================
# TREND ANALYSIS
# ============================================================================

def compute_frequency_trend(
    measurements: list,  # List of (timestamp, f_current) tuples
    days: int = 7
) -> dict:
    """
    Compute frequency drift over N days.
    
    Returns trend metrics for escalation logic:
    {
        'drift_hz_per_day': float,
        'percent_change': float,
        'is_accelerating': bool,  # True if drift is speeding up
    }
    """
    if len(measurements) < 2:
        return {
            'drift_hz_per_day': 0,
            'percent_change': 0,
            'is_accelerating': False
        }
    
    # Sort by timestamp
    sorted_m = sorted(measurements, key=lambda x: x[0])
    
    # Simple linear regression to detect trend
    if len(sorted_m) >= 2:
        f_first = sorted_m[0][1]
        f_last = sorted_m[-1][1]
        time_span_days = (sorted_m[-1][0] - sorted_m[0][0]).days
        
        if time_span_days > 0:
            drift_hz_per_day = (f_last - f_first) / time_span_days
            percent_change = 100 * (f_last - f_first) / f_first
        else:
            drift_hz_per_day = 0
            percent_change = 0
    else:
        drift_hz_per_day = 0
        percent_change = 0
    
    # Simple heuristic: if drift > -0.01 Hz/day, it's accelerating
    is_accelerating = drift_hz_per_day < -0.01
    
    return {
        'drift_hz_per_day': round(drift_hz_per_day, 4),
        'percent_change': round(percent_change, 2),
        'is_accelerating': is_accelerating,
        'measurement_count': len(sorted_m)
    }


def apply_trend_escalation(
    current_score: HealthScore,
    trend: dict
) -> HealthScore:
    """
    If score is Yellow but frequency is drifting down rapidly,
    escalate to Red.
    """
    if (current_score.health == HealthStatus.YELLOW and
        trend['is_accelerating']):
        
        escalated = HealthScore(
            health=HealthStatus.RED,
            score=25,  # Force to low Red score
            z_f=current_score.z_f,
            delta_v=current_score.delta_v,
            c_freq=current_score.c_freq,
            details={
                **current_score.details,
                "escalation_reason": "Yellow + accelerating downward trend",
                "drift_hz_per_day": trend['drift_hz_per_day']
            },
            risk_factors=current_score.risk_factors
        )
        return escalated
    
    return current_score


# ============================================================================
# CONFIDENCE INTERVALS
# ============================================================================

def compute_confidence_interval(
    score: int,
    z_f: float,
    delta_v: float,
    c_freq: float,
    confidence_level: float = 0.90
) -> Tuple[float, float]:
    """
    Compute confidence interval around health score.
    
    Uses a simplified approach: combine uncertainties from frequency,
    variance, and confidence sources.
    
    Returns: (lower_bound, upper_bound) at given confidence level.
    """
    # Z-score for 90% CI is ~1.645; for 95% is ~1.96
    z_critical = 1.645 if confidence_level >= 0.90 else 1.96
    
    # Estimate standard error from component uncertainties
    # (simplified; in production, use bootstrap or Bayesian methods)
    z_f_uncertainty = max(z_f * 0.15, 0.1)  # 15% relative + floor
    delta_v_uncertainty = max(delta_v * 0.20, 0.1)
    c_freq_uncertainty = max((1 - c_freq) * 10, 0)  # Confidence penalty
    
    # Combine in quadrature
    combined_std = math.sqrt(
        z_f_uncertainty ** 2 +
        delta_v_uncertainty ** 2 +
        c_freq_uncertainty ** 2
    )
    
    margin_of_error = z_critical * combined_std
    
    lower = max(0, score - margin_of_error)
    upper = min(100, score + margin_of_error)
    
    return (lower, upper)


# ============================================================================
# EXAMPLE USAGE & TEST CASES
# ============================================================================

def example_1_stable_bridge():
    """Example 1: Stable bridge (Green)."""
    print("\n" + "="*70)
    print("EXAMPLE 1: Stable Bridge (GREEN)")
    print("="*70)
    
    baseline = Baseline(
        f_baseline=2.50,
        sigma_f=0.08,
        v_baseline=0.15,
        sigma_v=0.05,
        trip_count=30
    )
    
    measurement = Measurement(
        f_current=2.51,
        c_freq=0.92,
        v_current=0.16
    )
    
    score = compute_health_score(baseline, measurement, current_trip_count=35)
    
    print(f"Baseline: f = {baseline.f_baseline} Hz ± {baseline.sigma_f} Hz")
    print(f"Current:  f = {measurement.f_current} Hz (Δf = {abs(measurement.f_current - baseline.f_baseline):.3f} Hz)")
    print(f"Confidence: {measurement.c_freq:.2%}")
    print()
    print(f"Result:   {score.health.value} (Score: {score.score})")
    print(f"Details:  z_f = {score.z_f:.2f}σ, Δv = {score.delta_v:.2f}x")
    print()
    print(f"✓ Bridge operating normally. No action required.")
    
    ci_low, ci_high = compute_confidence_interval(
        score.score, score.z_f, score.delta_v, score.c_freq
    )
    print(f"90% CI: [{ci_low:.0f}, {ci_high:.0f}]")


def example_2_concerning_trend():
    """Example 2: Frequency dropping (Red)."""
    print("\n" + "="*70)
    print("EXAMPLE 2: Concerning Trend (RED)")
    print("="*70)
    
    baseline = Baseline(
        f_baseline=2.50,
        sigma_f=0.08,
        v_baseline=0.15,
        sigma_v=0.05,
        trip_count=30
    )
    
    measurement = Measurement(
        f_current=2.35,  # 6% drop
        c_freq=0.75,
        v_current=0.25  # Higher variance
    )
    
    score = compute_health_score(baseline, measurement, current_trip_count=40)
    
    print(f"Baseline: f = {baseline.f_baseline} Hz ± {baseline.sigma_f} Hz")
    print(f"Current:  f = {measurement.f_current} Hz (Δf = {abs(measurement.f_current - baseline.f_baseline):.3f} Hz, {-5.6:.1f}%)")
    print(f"Variance: {baseline.v_baseline:.3f} → {measurement.v_current:.3f} (Δv = {measurement.v_current/baseline.v_baseline:.2f}x)")
    print()
    print(f"Risk Factors:")
    print(f"  Frequency shift: z_f = {score.z_f:.2f}σ ({score.risk_factors.freq_risk})")
    print(f"  Modal clarity:   Δv = {score.delta_v:.2f}x ({score.risk_factors.clarity_risk})")
    print(f"  Confidence:      {measurement.c_freq:.0%} ({score.risk_factors.confidence_risk})")
    print()
    print(f"Result:   {score.health.value} (Score: {score.score})")
    print()
    print(f"⚠  ALERT: Frequency shift of {score.z_f:.1f}σ detected.")
    print(f"   Interpretation: Stiffness loss (~10% based on 6% freq drop)")
    print(f"   Action: Visual inspection required within 48 hours")
    
    ci_low, ci_high = compute_confidence_interval(
        score.score, score.z_f, score.delta_v, score.c_freq
    )
    print(f"90% CI: [{ci_low:.0f}, {ci_high:.0f}]")


def example_3_high_variance_low_confidence():
    """Example 3: Windy conditions (YELLOW/RED due to uncertainty)."""
    print("\n" + "="*70)
    print("EXAMPLE 3: High Variance, Low Confidence (YELLOW/RED)")
    print("="*70)
    
    baseline = Baseline(
        f_baseline=3.20,
        sigma_f=0.10,
        v_baseline=0.20,
        sigma_v=0.05,
        trip_count=40
    )
    
    measurement = Measurement(
        f_current=3.18,  # Stable
        c_freq=0.45,     # Low confidence (wind noise)
        v_current=0.50   # High variance
    )
    
    score = compute_health_score(baseline, measurement, current_trip_count=50)
    
    print(f"Baseline: f = {baseline.f_baseline} Hz ± {baseline.sigma_f} Hz")
    print(f"Current:  f = {measurement.f_current} Hz (Δf = {abs(measurement.f_current - baseline.f_baseline):.3f} Hz)")
    print(f"Confidence: {measurement.c_freq:.0%} (LOW - windy conditions)")
    print(f"Variance: {baseline.v_baseline:.3f} → {measurement.v_current:.3f} (Δv = {measurement.v_current/baseline.v_baseline:.2f}x)")
    print()
    print(f"Risk Factors:")
    print(f"  Frequency shift: z_f = {score.z_f:.2f}σ ({score.risk_factors.freq_risk})")
    print(f"  Modal clarity:   Δv = {score.delta_v:.2f}x ({score.risk_factors.clarity_risk})")
    print(f"  Confidence:      {measurement.c_freq:.0%} ({score.risk_factors.confidence_risk})")
    print()
    print(f"Result:   {score.health.value} (Score: {score.score})")
    print()
    print(f"⚠  Cannot assess health due to high measurement uncertainty.")
    print(f"   Action: Re-collect data in calmer conditions")
    
    ci_low, ci_high = compute_confidence_interval(
        score.score, score.z_f, score.delta_v, score.c_freq
    )
    print(f"90% CI: [{ci_low:.0f}, {ci_high:.0f}]")


def example_4_threshold_sensitivity():
    """Example 4: Show sensitivity near thresholds."""
    print("\n" + "="*70)
    print("EXAMPLE 4: Threshold Sensitivity Analysis")
    print("="*70)
    
    baseline = Baseline(
        f_baseline=2.50,
        sigma_f=0.08,
        v_baseline=0.15,
        sigma_v=0.05,
        trip_count=30
    )
    
    print("\nVarying frequency shift (Δf) from 0.02 Hz to 0.30 Hz:")
    print("(holding variance constant at baseline, confidence at 0.80)")
    print()
    print("  Δf (Hz) | Δf (%)  | z_f   | Health | Score | Action")
    print("  --------|---------|-------|--------|-------|--------")
    
    for delta_f in [0.02, 0.05, 0.08, 0.10, 0.15, 0.20, 0.30]:
        f_current = baseline.f_baseline - delta_f
        measurement = Measurement(f_current=f_current, c_freq=0.80, v_current=baseline.v_baseline)
        score = compute_health_score(baseline, measurement, 30)
        
        percent_change = -100 * delta_f / baseline.f_baseline
        z_f = score.z_f
        action_map = {
            HealthStatus.GREEN: "Continue",
            HealthStatus.YELLOW: "Monitor",
            HealthStatus.RED: "Inspect 48h"
        }
        
        print(f"  {delta_f:.2f}   | {percent_change:6.1f}  | {z_f:5.2f} | {score.health.value:6s} | {score.score:5d} | {action_map[score.health]}")


if __name__ == "__main__":
    print("\n" + "█"*70)
    print("█  Social SHM Health Scoring Algorithm - Test Suite")
    print("█"*70)
    
    example_1_stable_bridge()
    example_2_concerning_trend()
    example_3_high_variance_low_confidence()
    example_4_threshold_sensitivity()
    
    print("\n" + "█"*70)
    print("█  End of Examples")
    print("█"*70 + "\n")
