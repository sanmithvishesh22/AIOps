"""D3-003.5 — the scaler controller: decide, wait, clamp, apply, write.

Per managed service (SCALER_SERVICES, default scope front-end per Decision 1):

  1. read current replicas from the scale client
  2. forecast load: per-service RPS at horizon H (reuses the forecast module's
     deterministic forecaster on the ``rps`` column; the safe scalar is the
     MAX over the horizon path, chosen predeclared below)
  3. policy: ``desired_replicas`` — pure map, fail-closed on missing anchor
  4. cooldown gate (up 30 s / down 300 s)
  5. bounds clamp (PS-3) — and the apply boundary re-clamps (D3-003.4)
  6. apply via the mockable scale client, retry-with-backoff; a service that
     keeps failing ABORTS the whole apply batch (never a half-applied set —
     k8s is not transactional, so the guarantee is: stop, log exact state,
     leave the remaining services untouched, recover on replay)
  7. write one ``scaler/replicas_target`` Contract-A row with
     meta={current, reason, cooldown_s, bounds, seed} (spec'd by D3-003.5)

Writes are deterministic per decision so a replay reproduces rows byte-for-byte
(PS-2/PS-4); cross-run de-duplication needs the store-side unique key already
requested by predict (Contract-A change, recorded not implemented here).
Run scalable rows are **instrument-quality mechanics** until D3-000.7 freezes
the ⚙️ capacity anchor: without one the controller refuses scored mode and
writes nothing.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from ..common import store
from ..forecast.model import ForecastResult, SeasonalForecaster
from ..forecast.pipeline import service_series
from . import config
from .cooldown import CooldownState, clamp_bounds, gate_scale, resolve_direction
from .k8s import ScaleAPIError, ScaleClient
from .policy import ScaleDecision, desired_replicas

logger = logging.getLogger("aiops.scaler")

MODULE = "scaler"
KIND = "replicas_target"


def _store_write(rows: list[dict]) -> int:
    store.normalize(rows)
    return store.write(rows)


@dataclass
class ServiceOutcome:
    """What the controller did (or refused) for one service."""
    service: str
    current: int
    forecast_rps: float | None
    target: int | None
    reason: str
    scaled: bool
    error: str | None = None


@dataclass
class ScaleRun:
    """One controller pass: decidable + auditable."""
    outcomes: list[ServiceOutcome] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    applied: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def refused(self) -> int:
        return sum(1 for o in self.outcomes if o.target is None and o.error)


class ScalerControllerError(Exception):
    """Apply batch aborted (fail-stop, exactly-once log: PS-3/PS-4)."""


class ScalerController:
    """Wires forecast → policy → cooldown → (clamped) apply → inference rows."""

    def __init__(
        self,
        client: ScaleClient,
        anchor_rps: float | None = None,
        anchor_provenance: str | None = None,
        services: tuple[str, ...] | None = None,
        forecaster: SeasonalForecaster | None = None,
        sink: Callable[[list[dict]], int] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.client = client
        # A capacity anchor passed here is DEFAULTED from env; the selftest
        # injects an explicitly-provenanced TEST anchor. No env => fail-closed.
        if anchor_rps is None:
            self.anchor = None
            self.anchor_provenance = "missing:SCALER_CAPACITY_RPS_unset"
        else:
            self.anchor = float(anchor_rps)
            self.anchor_provenance = anchor_provenance or "env:SCALER_CAPACITY_RPS"
        self.services = tuple(
            s.strip() for s in (services or config.SERVICES) if s.strip()
        )
        self.forecaster = forecaster or SeasonalForecaster()
        self.sink = sink or _store_write
        self.sleep = sleep or time.sleep
        self._state: dict[str, CooldownState] = {
            s: CooldownState() for s in self.services
        }
        if not self.services:
            raise ValueError("scaler needs at least one managed service")

    # ------------------------------------------------------------------
    def _forecast_rps(self, frame: pd.DataFrame, service: str) -> ForecastResult:
        series = service_series(frame, service, column="rps")
        return self.forecaster.forecast(series)

    def _apply(self, service: str, target: int, current: int) -> tuple[int, bool, int]:
        """Clamp→apply with retry/backoff; returns (applied_target, attempted, attempts)."""
        bounded, _ = clamp_bounds(target)
        if bounded == current:
            return bounded, False, 0        # no API call unless the count changes
        attempts = 0
        err: Exception | None = None
        for attempt in range(1, config.MAX_ATTEMPTS + 1):
            attempts = attempt
            try:
                return self.client.scale(service, bounded), True, attempts
            except ScaleAPIError as exc:
                err = exc
                logger.warning(
                    "scaler apply attempt %d/%d failed for %s: %s",
                    attempt, config.MAX_ATTEMPTS, service, exc,
                )
                if attempt < config.MAX_ATTEMPTS:
                    self.sleep(config.BACKOFF_S * attempt)
        raise ScaleAPIError(
            f"aborted after {attempts} attempts for {service}: {err}"
        ) from err

    # ------------------------------------------------------------------
    def run(self, frame: pd.DataFrame, now_ts: float | None = None) -> ScaleRun:
        if frame is None or frame.empty:
            raise ValueError("scaler frame is empty")
        ts = float(now_ts) if now_ts is not None else float(
            frame["ts"].max()
        )
        run = ScaleRun()
        targets: list[tuple[str, int, int]] = []

        # ---- decisions (pure; nothing applied yet) -----------------------
        for service in sorted(self.services):
            try:
                current = int(self.client.current_replicas(service))
            except Exception as exc:
                run.outcomes.append(ServiceOutcome(
                    service, -1, None, None, f"read_current_failed:{exc}", False,
                    error=str(exc),
                ))
                continue
            try:
                fc = self._forecast_rps(frame, service)
            except (ValueError, KeyError) as exc:
                run.outcomes.append(ServiceOutcome(
                    service, current, None, None, f"forecast_unavailable:{exc}",
                    False, error=str(exc),
                ))
                continue
            forecast_rps = float(np.max(fc.values)) if fc.values.size else float("nan")

            anchor = (
                None if self.anchor is None else
                _anchor(self.anchor, self.anchor_provenance)
            )
            try:
                decision: ScaleDecision = desired_replicas(
                    forecast_rps,
                    anchor,
                    service=service,
                    last_known_good=current,
                )
            except Exception as exc:               # PolicyRefusal + any guard
                run.outcomes.append(ServiceOutcome(
                    service, current, forecast_rps, None, f"refused:{exc}",
                    False, error=str(exc),
                ))
                continue

            bounded, clamped = clamp_bounds(decision.replicas)
            allowed, gate_reason = gate_scale(bounded, self._state[service], ts)
            if not allowed:
                run.outcomes.append(ServiceOutcome(
                    service, current, forecast_rps, bounded,
                    f"{decision.reason}|{gate_reason}|clamp={clamped}", False,
                ))
                continue
            run.outcomes.append(ServiceOutcome(
                service, current, forecast_rps, bounded,
                f"{decision.reason}|{gate_reason}|clamp={clamped}", False,
            ))
            targets.append((service, bounded, current))

        # ---- apply batch (stop-and-log on first failure, PS-3/PS-4) -------
        for i, (service, target, current) in enumerate(targets):
            try:
                applied, attempted, _attempts = self._apply(service, target, current)
            except ScaleAPIError as exc:
                remaining = [s for s, _t, _c in targets[i + 1:]]
                run.errors.append(
                    f"{service}: {exc} — batch aborted; services {remaining} "
                    "left untouched (recoverable on replay)"
                )
                break
            if attempted:
                direction = resolve_direction(applied, self._state[service])
                self._state[service] = CooldownState(
                    last_scale_ts=ts,
                    last_replicas=applied,
                    last_direction=direction if direction != "none" else None,
                )
                run.applied.append(service)
            run.outcomes = [
                ServiceOutcome(
                    o.service, o.current, o.forecast_rps,
                    applied, f"{o.reason}|scaled",
                    True, o.error,
                ) if o.service == service else o
                for o in run.outcomes
            ]

        # ---- Contract-A rows (deterministic per decision) -----------------
        for outcome in run.outcomes:
            if outcome.target is None or outcome.error:
                continue                       # never write rows for refusals
            reason = outcome.reason
            cooldown_s = config.COOLDOWN_UP_S if outcome.target >= outcome.current \
                else config.COOLDOWN_DOWN_S
            run.rows.append({
                "ts": ts,
                "module": MODULE,
                "service": outcome.service,
                "kind": KIND,
                "value": int(outcome.target),
                "meta": {
                    "current": int(outcome.current),
                    "reason": reason,
                    "cooldown_s": int(cooldown_s),
                    "bounds": [int(config.MIN_REPLICAS), int(config.MAX_REPLICAS)],
                    "seed": int(config.SEED),
                    "anchor_provenance": self.anchor_provenance,
                    "provisional": True,       # ⚙️ until D3-000.7 freezes anchors
                    "instrument_quality": True,
                },
            })
        return run

    def write_rows(self, run: ScaleRun) -> int:
        """Write ``run.rows`` via the configured sink (mock in selftest)."""
        if not run.rows:
            return 0
        return int(self.sink(run.rows))


def _anchor(rps: float, provenance: str):
    from .policy import CapacityAnchor

    return CapacityAnchor(float(rps), str(provenance))


__all__ = [
    "MODULE",
    "KIND",
    "ScaleRun",
    "ServiceOutcome",
    "ScalerController",
    "ScalerControllerError",
]
