"""Paired Sensitivity Analysis: Assessing the impact of excluding pair 19 (D3-008).

Compares:
  Baseline: All 29 completed matched pairs (28 capacity-responsive + 1 negative control)
  Sensitivity: 28 completed matched pairs excluding pair-stat-cpu_-19-02c20431 (27 capacity-responsive + 1 negative control)
"""
from __future__ import annotations

import argparse
import sys

from experiment.analysis.config import BOOTSTRAP_RESAMPLES, DEFAULT_SEED
from experiment.analysis.loader import load_pairs_from_db
from experiment.analysis.report import ExperimentAnalyzer

EXCLUDED_PAIR_ID = "pair-stat-cpu_-19-02c20431"


def run_sensitivity(dsn: str, resamples: int = BOOTSTRAP_RESAMPLES, seed: int = DEFAULT_SEED) -> int:
    import psycopg2

    conn = psycopg2.connect(dsn)
    all_pairs = load_pairs_from_db(conn)
    conn.close()

    print(f"Total pairs loaded from DB: {len(all_pairs)}")

    # Verify presence of excluded pair
    target = [p for p in all_pairs if p.pair_id == EXCLUDED_PAIR_ID]
    if not target:
        raise ValueError(f"Target pair {EXCLUDED_PAIR_ID} not found in database!")
    p19 = target[0]
    print(f"\nTarget Pair Details ({p19.pair_id}):")
    print(f"  Regime: {p19.workload_regime}, Fault: {p19.fault_class}, Control: {p19.is_negative_control}")
    print(
        f"  HPA: breach_dur={p19.hpa_breach_duration_s}s, breach_req={p19.hpa_breaching_requests}, "
        f"pod_min={p19.hpa_pod_minutes}, actions={p19.hpa_scaling_actions}, osc={p19.hpa_oscillations}"
    )
    print(
        f"  Hybrid: breach_dur={p19.hybrid_breach_duration_s}s, breach_req={p19.hybrid_breaching_requests}, "
        f"pod_min={p19.hybrid_pod_minutes}, actions={p19.hybrid_scaling_actions}, osc={p19.hybrid_oscillations}"
    )
    print("  Delta (Hybrid - HPA):")
    print(f"    Δ breach_dur = {p19.hybrid_breach_duration_s - p19.hpa_breach_duration_s:+.2f}s")
    print(f"    Δ breach_req = {p19.hybrid_breaching_requests - p19.hpa_breaching_requests:+d}")
    print(f"    Δ pod_min    = {p19.hybrid_pod_minutes - p19.hpa_pod_minutes:+.2f}")
    print(f"    Δ actions    = {p19.hybrid_scaling_actions - p19.hpa_scaling_actions:+d}")
    print(f"    Δ osc        = {p19.hybrid_oscillations - p19.hpa_oscillations:+d}")

    pairs_sensitivity = [p for p in all_pairs if p.pair_id != EXCLUDED_PAIR_ID]
    print(f"\nFiltered pairs count (sensitivity): {len(pairs_sensitivity)}")

    # 1. Baseline analysis
    analyzer_base = ExperimentAnalyzer(all_pairs, n_resamples=resamples, seed=seed)
    rep_base = analyzer_base.generate_report()
    text_base = analyzer_base.render_text()

    # 2. Sensitivity analysis
    analyzer_sens = ExperimentAnalyzer(pairs_sensitivity, n_resamples=resamples, seed=seed)
    rep_sens = analyzer_sens.generate_report()
    text_sens = analyzer_sens.render_text()

    print("\n" + "=" * 78)
    print(f"BASELINE ANALYSIS (All {len(all_pairs)} Matched Pairs / {len(rep_base['capacity_responsive']['primaries'] and all_pairs)-1} Capacity-Responsive)")
    print("=" * 78)
    print(text_base)

    print("\n" + "=" * 78)
    print(f"SENSITIVITY ANALYSIS (Excluding {EXCLUDED_PAIR_ID} / {len(pairs_sensitivity)-1} Capacity-Responsive)")
    print("=" * 78)
    print(text_sens)

    # Detailed side-by-side comparison table
    print("\n" + "=" * 78)
    print("SIDE-BY-SIDE NUMERICAL COMPARISON (Capacity-Responsive Subsets)")
    print("=" * 78)
    n_base = len(all_pairs) - 1
    n_sens = len(pairs_sensitivity) - 1
    print(f"{'Metric':<25} | {f'Baseline (N={n_base})':<38} | {f'Sensitivity (N={n_sens})':<38} | {'Shift (Δ_sens - Δ_base)'}")
    print("-" * 120)

    base_prim = rep_base["capacity_responsive"]["primaries"]
    sens_prim = rep_sens["capacity_responsive"]["primaries"]
    base_sec = rep_base["capacity_responsive"]["secondaries"]
    sens_sec = rep_sens["capacity_responsive"]["secondaries"]

    for m in ["slo_breach_duration_s", "breaching_requests"]:
        b = base_prim[m]
        s = sens_prim[m]
        b_str = f"Mean={b['mean_delta']:+.2f} [{b['ci_lower']:+.2f}, {b['ci_upper']:+.2f}] dz={b['effect_size_dz']:.4f}"
        s_str = f"Mean={s['mean_delta']:+.2f} [{s['ci_lower']:+.2f}, {s['ci_upper']:+.2f}] dz={s['effect_size_dz']:.4f}"
        diff = s["mean_delta"] - b["mean_delta"]
        print(f"{m:<25} | {b_str:<38} | {s_str:<38} | {diff:+.2f}")

    for m in ["pod_minutes", "scaling_actions", "oscillations"]:
        b = base_sec[m]
        s = sens_sec[m]
        b_str = f"Mean={b['mean_delta']:+.2f} [{b['ci_lower']:+.2f}, {b['ci_upper']:+.2f}] dz={b['effect_size_dz']:.4f}"
        s_str = f"Mean={s['mean_delta']:+.2f} [{s['ci_lower']:+.2f}, {s['ci_upper']:+.2f}] dz={s['effect_size_dz']:.4f}"
        diff = s["mean_delta"] - b["mean_delta"]
        print(f"{m:<25} | {b_str:<38} | {s_str:<38} | {diff:+.2f}")

    print("-" * 120)
    return 0


def main():
    parser = argparse.ArgumentParser(description="Paired sensitivity analysis excluding pair 19")
    parser.add_argument("--dsn", default="postgresql://aiops:aiops@localhost:5432/aiops", help="TimescaleDB DSN")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Master RNG seed")
    parser.add_argument("--resamples", type=int, default=BOOTSTRAP_RESAMPLES, help="Number of bootstrap resamples")
    args = parser.parse_args()

    try:
        sys.exit(run_sensitivity(dsn=args.dsn, resamples=args.resamples, seed=args.seed))
    except Exception as e:
        print(f"Error executing sensitivity analysis: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
