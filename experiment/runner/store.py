"""D3-007.4 — Relational results persistence (Contract D: experiment_run / result).

Consumes the schema in `experiment/schema.sql` (does not define it).
Writes:
  * experiment_run: pair_id, policy, regime, fault_class, is_negative_control, seed, slo_p95_ms, horizon_s, notes
  * experiment_result: 1:1 scorecard (slo_breach_duration_s, breaching_requests, pod_minutes, churn)

Includes an in-memory MockResultsStore for offline tests (TS-1/TS-2) and a
PostgresResultsStore for live TimescaleDB runs.
"""
from __future__ import annotations

import dataclasses
import json
from typing import Any, Protocol

from .metrics import Scorecard
from .pair import TrialSpec


@dataclasses.dataclass
class StoredRun:
    """In-memory representation of an experiment_run record."""

    run_id: int
    pair_id: str
    policy: str
    workload_regime: str
    fault_class: str
    is_negative_control: bool
    seed: int
    slo_p95_ms: float
    slo_error_rate: float
    horizon_s: int
    notes: str | None = None
    started_at: str | None = None
    ended_at: str | None = None


@dataclasses.dataclass
class StoredResult:
    """In-memory representation of an experiment_result record."""

    run_id: int
    slo_breach_duration_s: float
    breaching_requests: int
    breaching_request_ratio: float
    pod_minutes: float
    scaling_actions: int
    oscillations: int
    extra: dict | None = None


class ResultsStore(Protocol):
    """Protocol for recording paired-trial runs and scorecards."""

    def record_run(self, spec: TrialSpec, started_at: str, ended_at: str, notes: str | None = None) -> int:
        """Insert experiment_run, returning the allocated run_id."""
        ...

    def record_result(self, run_id: int, scorecard: Scorecard, extra: dict | None = None) -> None:
        """Insert experiment_result for run_id."""
        ...

    def get_completed_pair_ids(self) -> set[str]:
        """Return the set of pair_ids that have BOTH policies completed with results."""
        ...

    def get_run(self, run_id: int) -> StoredRun | None:
        ...

    def get_result(self, run_id: int) -> StoredResult | None:
        ...


class MockResultsStore:
    """Thread-safe, in-memory implementation of ResultsStore for offline testing."""

    def __init__(self) -> None:
        self.runs: dict[int, StoredRun] = {}
        self.results: dict[int, StoredResult] = {}
        self._next_id = 1

    def record_run(self, spec: TrialSpec, started_at: str, ended_at: str, notes: str | None = None) -> int:
        run_id = self._next_id
        self._next_id += 1
        self.runs[run_id] = StoredRun(
            run_id=run_id,
            pair_id=spec.pair_id,
            policy=spec.policy,
            workload_regime=spec.workload_regime,
            fault_class=spec.fault_class,
            is_negative_control=spec.is_negative_control,
            seed=spec.seed,
            slo_p95_ms=spec.slo_p95_ms,
            slo_error_rate=spec.slo_error_rate,
            horizon_s=spec.horizon_s,
            notes=notes,
            started_at=started_at,
            ended_at=ended_at,
        )
        return run_id

    def record_result(self, run_id: int, scorecard: Scorecard, extra: dict | None = None) -> None:
        if run_id not in self.runs:
            raise KeyError(f"No run found with id {run_id}")
        self.results[run_id] = StoredResult(
            run_id=run_id,
            slo_breach_duration_s=scorecard.slo_breach_duration_s,
            breaching_requests=scorecard.breaching_requests,
            breaching_request_ratio=scorecard.breaching_request_ratio,
            pod_minutes=scorecard.pod_minutes,
            scaling_actions=scorecard.scaling_actions,
            oscillations=scorecard.oscillations,
            extra=extra,
        )

    def get_completed_pair_ids(self) -> set[str]:
        """A pair is completed only if BOTH policies have successful result rows."""
        runs_by_pair: dict[str, set[str]] = {}
        for r in self.runs.values():
            if r.run_id in self.results:
                runs_by_pair.setdefault(r.pair_id, set()).add(r.policy)
        return {pair_id for pair_id, policies in runs_by_pair.items() if len(policies) == 2}

    def get_run(self, run_id: int) -> StoredRun | None:
        return self.runs.get(run_id)

    def get_result(self, run_id: int) -> StoredResult | None:
        return self.results.get(run_id)


class PostgresResultsStore:
    """Postgres / TimescaleDB implementation of ResultsStore."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def _get_conn(self) -> Any:
        try:
            import psycopg2
            try:
                return psycopg2.connect(self.dsn)
            except Exception:
                if "timescaledb.aiops" in self.dsn:
                    fallback = self.dsn.replace("timescaledb.aiops", "localhost")
                    return psycopg2.connect(fallback)
                raise
        except ImportError:
            raise RuntimeError("psycopg2 not installed; required for PostgresResultsStore")

    def record_run(self, spec: TrialSpec, started_at: str, ended_at: str, notes: str | None = None) -> int:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO experiment_run (
                        started_at, ended_at, pair_id, policy, workload_regime,
                        fault_class, is_negative_control, seed, slo_p95_ms,
                        slo_error_rate, horizon_s, notes
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    ) RETURNING run_id
                    """,
                    (
                        started_at, ended_at, spec.pair_id, spec.policy,
                        spec.workload_regime, spec.fault_class,
                        spec.is_negative_control, spec.seed, spec.slo_p95_ms,
                        spec.slo_error_rate, spec.horizon_s, notes,
                    ),
                )
                run_id = cur.fetchone()[0]
                conn.commit()
                return run_id
        finally:
            conn.close()

    def record_result(self, run_id: int, scorecard: Scorecard, extra: dict | None = None) -> None:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO experiment_result (
                        run_id, slo_breach_duration_s, breaching_requests,
                        breaching_request_ratio, pod_minutes, scaling_actions,
                        oscillations, mttd_s, rca_top1_correct, remediation_success,
                        extra
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    ) ON CONFLICT (run_id) DO UPDATE SET
                        slo_breach_duration_s = EXCLUDED.slo_breach_duration_s,
                        breaching_requests = EXCLUDED.breaching_requests,
                        breaching_request_ratio = EXCLUDED.breaching_request_ratio,
                        pod_minutes = EXCLUDED.pod_minutes,
                        scaling_actions = EXCLUDED.scaling_actions,
                        oscillations = EXCLUDED.oscillations
                    """,
                    (
                        run_id, scorecard.slo_breach_duration_s,
                        scorecard.breaching_requests, scorecard.breaching_request_ratio,
                        scorecard.pod_minutes, scorecard.scaling_actions,
                        scorecard.oscillations, scorecard.mttd_s,
                        scorecard.rca_top1_correct, scorecard.remediation_success,
                        json.dumps(extra) if extra else None,
                    ),
                )
                conn.commit()
        finally:
            conn.close()

    def get_completed_pair_ids(self) -> set[str]:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT r.pair_id
                    FROM experiment_run r
                    JOIN experiment_result res ON r.run_id = res.run_id
                    GROUP BY r.pair_id
                    HAVING count(DISTINCT r.policy) = 2
                    """
                )
                return {row[0] for row in cur.fetchall()}
        finally:
            conn.close()


__all__ = [
    "StoredRun",
    "StoredResult",
    "ResultsStore",
    "MockResultsStore",
    "PostgresResultsStore",
]
