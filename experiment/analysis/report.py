"""D3-008.2 / D3-008.3 — Analysis reporting and negative-control segregation.

Produces:
  1. Primary metrics (slo_breach_duration_s, breaching_requests) with 95% bootstrap CIs
  2. Secondary metrics (pod_minutes [cost], scaling_actions [churn], oscillations)
  3. Separate Negative-Control section (null results reported as-is, never buried)
  4. Machine-readable dict output and human-readable text report.
"""
from __future__ import annotations

import dataclasses
import json
from typing import Any, Dict, List, Sequence

from . import config
from .paired import BootstrapResult, PairedComparison, paired_bootstrap


@dataclasses.dataclass
class MatchedPairOutcome:
    """Full outcome record for one matched pair across both policies."""

    pair_id: str
    workload_regime: str
    fault_class: str
    is_negative_control: bool
    hpa_breach_duration_s: float
    hybrid_breach_duration_s: float
    hpa_breaching_requests: int
    hybrid_breaching_requests: int
    hpa_pod_minutes: float
    hybrid_pod_minutes: float
    hpa_scaling_actions: int
    hybrid_scaling_actions: int
    hpa_oscillations: int
    hybrid_oscillations: int


class ExperimentAnalyzer:
    """Analyzes a set of matched pair outcomes according to §9 and D3-008 specifications."""

    def __init__(
        self,
        pairs: Sequence[MatchedPairOutcome],
        n_resamples: int = config.BOOTSTRAP_RESAMPLES,
        confidence_level: float = config.CONFIDENCE_LEVEL,
        seed: int = config.DEFAULT_SEED,
    ):
        self.pairs = list(pairs)
        self.n_resamples = n_resamples
        self.confidence_level = confidence_level
        self.seed = seed

    def partition_controls(self) -> tuple[List[MatchedPairOutcome], List[MatchedPairOutcome]]:
        """Segregate capacity-responsive faults from negative controls (D3-008.3)."""
        responsive: List[MatchedPairOutcome] = []
        controls: List[MatchedPairOutcome] = []
        for p in self.pairs:
            if p.is_negative_control:
                controls.append(p)
            else:
                responsive.append(p)
        return responsive, controls

    def analyze_subset(
        self,
        subset: Sequence[MatchedPairOutcome],
        label: str,
        seed_offset: int = 0,
    ) -> Dict[str, Any]:
        """Compute primary and secondary bootstrap results for a subset of pairs."""
        n = len(subset)
        if n == 0:
            return {
                "subset": label,
                "n_pairs": 0,
                "primaries": {},
                "secondaries": {},
            }

        # Primaries
        delta_breach_dur = [p.hybrid_breach_duration_s - p.hpa_breach_duration_s for p in subset]
        delta_breach_req = [float(p.hybrid_breaching_requests - p.hpa_breaching_requests) for p in subset]

        ci_breach_dur = paired_bootstrap(
            delta_breach_dur,
            metric_name="slo_breach_duration_s",
            n_resamples=self.n_resamples,
            confidence_level=self.confidence_level,
            seed=self.seed + seed_offset + 1,
        )
        ci_breach_req = paired_bootstrap(
            delta_breach_req,
            metric_name="breaching_requests",
            n_resamples=self.n_resamples,
            confidence_level=self.confidence_level,
            seed=self.seed + seed_offset + 2,
        )

        # Secondaries (cost & churn)
        delta_pod_mins = [p.hybrid_pod_minutes - p.hpa_pod_minutes for p in subset]
        delta_actions = [float(p.hybrid_scaling_actions - p.hpa_scaling_actions) for p in subset]
        delta_osc = [float(p.hybrid_oscillations - p.hpa_oscillations) for p in subset]

        ci_pod_mins = paired_bootstrap(
            delta_pod_mins,
            metric_name="pod_minutes",
            n_resamples=self.n_resamples,
            confidence_level=self.confidence_level,
            seed=self.seed + seed_offset + 3,
        )
        ci_actions = paired_bootstrap(
            delta_actions,
            metric_name="scaling_actions",
            n_resamples=self.n_resamples,
            confidence_level=self.confidence_level,
            seed=self.seed + seed_offset + 4,
        )
        ci_osc = paired_bootstrap(
            delta_osc,
            metric_name="oscillations",
            n_resamples=self.n_resamples,
            confidence_level=self.confidence_level,
            seed=self.seed + seed_offset + 5,
        )

        return {
            "subset": label,
            "n_pairs": n,
            "primaries": {
                "slo_breach_duration_s": ci_breach_dur.to_dict(),
                "breaching_requests": ci_breach_req.to_dict(),
            },
            "secondaries": {
                "pod_minutes": ci_pod_mins.to_dict(),
                "scaling_actions": ci_actions.to_dict(),
                "oscillations": ci_osc.to_dict(),
            },
        }

    def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive analysis with strictly segregated negative controls."""
        responsive, controls = self.partition_controls()

        res_analysis = self.analyze_subset(responsive, label="capacity_responsive", seed_offset=0)
        ctl_analysis = self.analyze_subset(controls, label="negative_controls", seed_offset=100)

        return {
            "confidence_level": self.confidence_level,
            "bootstrap_resamples": self.n_resamples,
            "seed": self.seed,
            "total_pairs": len(self.pairs),
            "capacity_responsive": res_analysis,
            "negative_controls": ctl_analysis,
        }

    def render_text(self) -> str:
        """Render a formatted human-readable report."""
        rep = self.generate_report()
        lines: List[str] = [
            "=" * 78,
            "CAPSTONE AIOPS — D3-008 PAIRED TRIAL STATISTICAL ANALYSIS",
            f"Confidence: {int(self.confidence_level * 100)}% Bootstrap CI | Resamples: {self.n_resamples} | Seed: {self.seed}",
            f"Total Completed Matched Pairs: {rep['total_pairs']}",
            "=" * 78,
            "",
            "### SECTION 1: CAPACITY-RESPONSIVE FAULTS (CONFIRMATORY)",
            f"Evaluated Pairs: {rep['capacity_responsive']['n_pairs']}",
        ]

        if rep["capacity_responsive"]["n_pairs"] == 0:
            lines.append("  (No capacity-responsive pairs provided)")
        else:
            lines.append("  [Primary Metrics: Reliability]")
            p = rep["capacity_responsive"]["primaries"]
            for m in ["slo_breach_duration_s", "breaching_requests"]:
                data = p[m]
                sig = "*" if data["significant"] else " "
                warn = f" ({data['warning']})" if data["warning"] else ""
                lines.append(
                    f"  {sig} {m:24s}: Mean Δ = {data['mean_delta']:+9.2f} "
                    f"[{data['ci_lower']:+9.2f}, {data['ci_upper']:+9.2f}] "
                    f"d_z = {data['effect_size_dz']}{warn}"
                )

            lines.append("")
            lines.append("  [Secondary Metrics: Resource & Churn]")
            s = rep["capacity_responsive"]["secondaries"]
            for m in ["pod_minutes", "scaling_actions", "oscillations"]:
                data = s[m]
                sig = "*" if data["significant"] else " "
                warn = f" ({data['warning']})" if data["warning"] else ""
                lines.append(
                    f"  {sig} {m:24s}: Mean Δ = {data['mean_delta']:+9.2f} "
                    f"[{data['ci_lower']:+9.2f}, {data['ci_upper']:+9.2f}] "
                    f"d_z = {data['effect_size_dz']}{warn}"
                )

        lines.extend([
            "",
            "-" * 78,
            "### SECTION 2: NEGATIVE CONTROLS (SEPARATE REPORTING)",
            "CRITICAL PROTOCOL: Null results printed as-is. Guard against false attribution.",
            f"Evaluated Negative Control Pairs: {rep['negative_controls']['n_pairs']}",
        ])

        if rep["negative_controls"]["n_pairs"] == 0:
            lines.append("  (No negative control pairs provided)")
        else:
            lines.append("  [Negative Control Metrics: Expected Null]")
            p = rep["negative_controls"]["primaries"]
            for m in ["slo_breach_duration_s", "breaching_requests"]:
                data = p[m]
                sig = "ALERT: NON-NULL" if data["significant"] else "CONFIRMED NULL"
                warn = f" ({data['warning']})" if data["warning"] else ""
                lines.append(
                    f"  - {m:24s}: Mean Δ = {data['mean_delta']:+9.2f} "
                    f"[{data['ci_lower']:+9.2f}, {data['ci_upper']:+9.2f}] -> {sig}{warn}"
                )

        lines.extend([
            "",
            "=" * 78,
            "NOTE: Δ = forecast_hybrid - hpa_tuned. Negative Δ indicates hybrid improvement.",
            "=" * 78,
        ])

        return "\n".join(lines)


__all__ = [
    "MatchedPairOutcome",
    "ExperimentAnalyzer",
]
