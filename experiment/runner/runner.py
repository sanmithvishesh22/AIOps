"""D3-007 — Paired-trial matrix runner and orchestration.

Coordinates execution of matched pairs across:
  4 regimes × 6 faults × ≥20 reps
Resumable by pair_id (D3-007.3 / PS-4).
Atomic pairs: if either trial fails, the pair is discarded (D3-007.1 edge).
"""
from __future__ import annotations

import datetime
import logging
import time
from typing import Callable, Protocol, Sequence

from . import config
from .metrics import Scorecard, TelemetryPoint, compute_scorecard
from .pair import MatchedPair, TrialSpec, build_matrix
from .store import MockResultsStore, ResultsStore

logger = logging.getLogger("aiops.experiment.runner")


class TrialExecutor(Protocol):
    """Protocol for executing a single trial spec and returning telemetry points."""

    def execute(self, spec: TrialSpec) -> list[TelemetryPoint]:
        ...


class MockTrialExecutor:
    """Mock executor for deterministic offline verification (TS-1/TS-2)."""

    def __init__(self, failure_filter: Callable[[TrialSpec], bool] | None = None) -> None:
        self.executed_specs: list[TrialSpec] = []
        self.failure_filter = failure_filter

    def execute(self, spec: TrialSpec) -> list[TelemetryPoint]:
        self.executed_specs.append(spec)
        if self.failure_filter and self.failure_filter(spec):
            raise RuntimeError(f"Mock execution failure injected for {spec.policy} in {spec.pair_id}")

        # Synthesize realistic deterministic telemetry (TS-6)
        # Higher latency for hpa_tuned on spike/bursty; lower for forecast_hybrid on diurnal
        base_p95 = 20.0
        if spec.policy == "hpa_tuned" and spec.workload_regime in ("spike", "bursty"):
            base_p95 = 350.0  # breach SLO (>300ms)
        elif spec.fault_class == "cpu_stress":
            base_p95 = 320.0 if spec.policy == "hpa_tuned" else 150.0

        n_steps = spec.duration_s // config.STEP_S
        points: list[TelemetryPoint] = []
        now = 1700000000.0

        for i in range(n_steps):
            t = now + i * config.STEP_S
            p = TelemetryPoint(
                ts=t,
                p95_ms=base_p95,
                error_rate=0.002,
                rps=30.0,
                replicas=2 if spec.policy == "hpa_tuned" else 4,
                is_infected=(n_steps // 2 <= i <= n_steps // 2 + 10),
            )
            points.append(p)
        return points


class PairedRunner:
    """Orchestrates execution of the matched-pair trial matrix."""

    def __init__(
        self,
        store: ResultsStore,
        executor: TrialExecutor,
        reps_per_cell: int = config.MIN_REPS_PER_CELL,
        master_seed: int = config.MASTER_SEED,
        regimes: Sequence[str] = config.REGIMES,
        faults: Sequence[str] = config.FAULT_CLASSES,
        duration_s: int | None = None,
    ) -> None:
        self.store = store
        self.executor = executor
        self.reps_per_cell = reps_per_cell
        self.master_seed = master_seed
        self.regimes = regimes
        self.faults = faults
        self.duration_s = duration_s

    def run_matrix(
        self,
        stop_on_first_error: bool = False,
        limit_pairs: int | None = None,
    ) -> dict[str, int]:
        """Execute the matrix, skipping completed pairs (resumable, PS-4)."""
        matrix = build_matrix(
            reps=self.reps_per_cell,
            master_seed=self.master_seed,
            regimes=self.regimes,
            faults=self.faults,
            duration_s=self.duration_s,
        )
        completed_pairs = self.store.get_completed_pair_ids()
        stats = {"total_pairs": len(matrix), "skipped": 0, "completed": 0, "discarded": 0}

        attempted = 0
        for pair in matrix:
            if pair.pair_id in completed_pairs:
                stats["skipped"] += 1
                continue

            if limit_pairs is not None and attempted >= limit_pairs:
                break

            success = self.run_pair(pair)
            attempted += 1
            if success:
                stats["completed"] += 1
                completed_pairs.add(pair.pair_id)
            else:
                stats["discarded"] += 1
                if stop_on_first_error:
                    break

        return stats

    def run_pair(self, pair: MatchedPair) -> bool:
        """Execute both trials of a matched pair in their randomized order.

        D3-007.1: If either trial fails, the pair is discarded (never a half-pair).
        """
        trial_a, trial_b = pair.trials()
        runs_to_record: list[tuple[TrialSpec, Scorecard, str, str]] = []

        for trial in (trial_a, trial_b):
            t_start = datetime.datetime.now(datetime.timezone.utc).isoformat()
            try:
                points = self.executor.execute(trial)
            except Exception as e:
                logger.error(
                    "Trial failed for pair %s policy %s: %s — discarding pair",
                    pair.pair_id, trial.policy, e
                )
                return False  # Discard pair (D3-007.1 edge)

            t_end = datetime.datetime.now(datetime.timezone.utc).isoformat()
            scorecard = compute_scorecard(points)
            runs_to_record.append((trial, scorecard, t_start, t_end))

        # Both succeeded -> commit to results store
        for trial, scorecard, t_start, t_end in runs_to_record:
            run_id = self.store.record_run(
                trial,
                started_at=t_start,
                ended_at=t_end,
                notes=f"matched_pair:{pair.pair_id};order:{pair.ordered_policies}",
            )
            self.store.record_result(run_id, scorecard)

        return True


__all__ = [
    "TrialExecutor",
    "MockTrialExecutor",
    "PairedRunner",
]
