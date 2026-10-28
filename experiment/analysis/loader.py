"""Loader to convert stored experiment runs and results into MatchedPairOutcome objects."""
from __future__ import annotations

from typing import Dict, List

from .report import MatchedPairOutcome


def load_pairs_from_db(conn) -> List[MatchedPairOutcome]:
    """Query TimescaleDB/Postgres for matched pairs that have both hpa_tuned and forecast_hybrid runs."""
    cur = conn.cursor()
    query = """
        SELECT 
            r.pair_id,
            r.policy,
            r.workload_regime,
            r.fault_class,
            r.is_negative_control,
            res.slo_breach_duration_s,
            res.breaching_requests,
            res.pod_minutes,
            res.scaling_actions,
            res.oscillations
        FROM experiment_run r
        JOIN experiment_result res ON r.run_id = res.run_id
        WHERE r.pair_id IS NOT NULL
        ORDER BY r.pair_id, r.policy;
    """
    cur.execute(query)
    rows = cur.fetchall()

    grouped: Dict[str, Dict[str, dict]] = {}
    meta: Dict[str, dict] = {}
    for row in rows:
        pair_id, policy, regime, fault, is_neg, breach_dur, breach_req, pod_min, actions, osc = row
        if pair_id not in grouped:
            grouped[pair_id] = {}
            meta[pair_id] = {
                "regime": regime,
                "fault": fault,
                "is_negative_control": is_neg,
            }
        grouped[pair_id][policy] = {
            "breach_dur": float(breach_dur or 0.0),
            "breach_req": int(breach_req or 0),
            "pod_min": float(pod_min or 0.0),
            "actions": int(actions or 0),
            "osc": int(osc or 0),
        }

    outcomes: List[MatchedPairOutcome] = []
    for pair_id, policies in grouped.items():
        if "hpa_tuned" in policies and "forecast_hybrid" in policies:
            hpa = policies["hpa_tuned"]
            hyb = policies["forecast_hybrid"]
            m = meta[pair_id]
            outcomes.append(
                MatchedPairOutcome(
                    pair_id=pair_id,
                    workload_regime=m["regime"],
                    fault_class=m["fault"],
                    is_negative_control=m["is_negative_control"],
                    hpa_breach_duration_s=hpa["breach_dur"],
                    hybrid_breach_duration_s=hyb["breach_dur"],
                    hpa_breaching_requests=hpa["breach_req"],
                    hybrid_breaching_requests=hyb["breach_req"],
                    hpa_pod_minutes=hpa["pod_min"],
                    hybrid_pod_minutes=hyb["pod_min"],
                    hpa_scaling_actions=hpa["actions"],
                    hybrid_scaling_actions=hyb["actions"],
                    hpa_oscillations=hpa["osc"],
                    hybrid_oscillations=hyb["osc"],
                )
            )

    return outcomes
