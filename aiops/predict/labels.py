"""Forward-only SLO breach labels for D3-001.

Decision 1/6 from ``experiment/DECISIONS.md``:

* breach window: p95 > SLO p95 **or** error rate > SLO error rate;
* severity: none / minor (p95 <= 450 ms) / major (p95 > 450 ms or error breach);
* prediction target: a **major** breach occurs within ``(t, t + H]``;
* ``dur_est_s``: observed major-breach duration in that window, clipped to
  ``[0, H]`` (a severity proxy, not a causal measurement).

The label window is strictly forward: the row at ``t`` is excluded, because the
predictor must not be handed the outcome it is trying to predict.  A NaN metric
is never fabricated into a breach.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import config

KEY_COLUMNS = ["ts", "service"]
LABEL_COLUMNS = ["y_major", "dur_est_s", "label_valid"]


@dataclass(frozen=True)
class SeverityThresholds:
    slo_p95_ms: float
    major_p95_ms: float
    slo_error_rate: float


def thresholds(
    slo_p95_ms: float | None = None,
    major_p95_ms: float | None = None,
    slo_error_rate: float | None = None,
) -> SeverityThresholds:
    cfg = SeverityThresholds(
        slo_p95_ms=float(config.SLO_P95_MS if slo_p95_ms is None else slo_p95_ms),
        major_p95_ms=float(
            config.SLO_MAJOR_P95_MS if major_p95_ms is None else major_p95_ms
        ),
        slo_error_rate=float(
            config.SLO_ERROR_RATE if slo_error_rate is None else slo_error_rate
        ),
    )
    if cfg.slo_p95_ms <= 0 or cfg.major_p95_ms <= 0:
        raise ValueError("SLO thresholds must be > 0")
    if cfg.major_p95_ms < cfg.slo_p95_ms:
        raise ValueError("major_p95_ms must be >= slo_p95_ms")
    if not 0.0 <= cfg.slo_error_rate <= 1.0:
        raise ValueError("slo_error_rate must be in [0, 1]")
    return cfg


def severity_masks(
    frame: pd.DataFrame,
    cfg: SeverityThresholds | None = None,
) -> tuple[pd.Series, pd.Series]:
    """Return ``(major, minor)`` boolean masks; NaN metrics grade as non-breaches."""
    cfg = cfg or thresholds()
    missing = [c for c in ("p95_ms", "error_rate") if c not in frame.columns]
    if missing:
        raise ValueError(f"severity needs columns: {missing}")
    p95 = pd.to_numeric(frame["p95_ms"], errors="coerce").astype(float)
    err = pd.to_numeric(frame["error_rate"], errors="coerce").astype(float)
    major = p95.gt(cfg.major_p95_ms) | err.gt(cfg.slo_error_rate)
    minor = (~major) & p95.gt(cfg.slo_p95_ms) & p95.le(cfg.major_p95_ms)
    return major.fillna(False), minor.fillna(False)


def _empty_labels(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["y_major"] = pd.Series(dtype="bool")
    out["dur_est_s"] = pd.Series(dtype="float64")
    out["label_valid"] = pd.Series(dtype="bool")
    return out


def classify_failure_mode(
    p95_ms: float,
    error_rate: float,
    cfg: SeverityThresholds | None = None,
) -> str:
    """D3-009.1 — Richer per-service failure-mode taxonomy.
    Categories: 'none', 'latency_breach', 'error_breach', 'compound_breach'.
    """
    cfg = cfg or thresholds()
    lat = float(p95_ms) > cfg.slo_p95_ms if np.isfinite(p95_ms) else False
    err = float(error_rate) > cfg.slo_error_rate if np.isfinite(error_rate) else False
    if lat and err:
        return "compound_breach"
    if lat:
        return "latency_breach"
    if err:
        return "error_breach"
    return "none"


def label_frame(
    frame: pd.DataFrame,
    horizon_s: int | float | None = None,
    slo_p95_ms: float | None = None,
    major_p95_ms: float | None = None,
    slo_error_rate: float | None = None,
    enable_taxonomy: bool | None = None,
) -> pd.DataFrame:
    """Attach ``y_major``, ``dur_est_s`` and ``label_valid`` to a Contract-C frame.

    When ``enable_taxonomy`` is True (D3-009), attaches optional ``failure_mode``.
    When disabled (default), columns and metrics are byte-identical.
    """
    if frame is None:
        raise ValueError("label frame is None")
    missing = [c for c in KEY_COLUMNS + ["p95_ms", "error_rate"] if c not in frame.columns]
    if missing:
        raise ValueError(f"label frame missing columns: {missing}")
    out = frame.copy().reset_index(drop=True)
    if out.empty:
        return _empty_labels(out)

    horizon = int(config.HORIZON_S if horizon_s is None else horizon_s)
    if horizon <= 0:
        raise ValueError(f"horizon_s must be > 0, got {horizon}")
    cfg = thresholds(slo_p95_ms, major_p95_ms, slo_error_rate)
    use_taxonomy = config.ENABLE_TAXONOMY if enable_taxonomy is None else bool(enable_taxonomy)

    out["ts"] = pd.to_numeric(out["ts"], errors="raise").astype(float)
    if not np.isfinite(out["ts"]).all():
        raise ValueError("label frame contains non-finite timestamps")
    if out["service"].isna().any():
        raise ValueError("label frame contains null service labels")
    out["service"] = out["service"].astype(str)
    if out.duplicated(KEY_COLUMNS).any():
        raise ValueError("duplicate (ts, service) rows are ambiguous for label windows")

    major_mask, _ = severity_masks(out, cfg)
    major = major_mask.to_numpy(dtype=bool)

    y_major = np.zeros(len(out), dtype=bool)
    dur_est = np.zeros(len(out), dtype=float)
    valid = np.zeros(len(out), dtype=bool)
    failure_mode = np.full(len(out), "none", dtype=object)

    for _, positions in out.groupby("service", sort=False).groups.items():
        pos = np.asarray(positions, dtype=int)
        order = np.argsort(out.loc[pos, "ts"].to_numpy(dtype=float), kind="mergesort")
        pos = pos[order]
        times = out.loc[pos, "ts"].to_numpy(dtype=float)
        service_major = major[pos]
        service_p95 = out.loc[pos, "p95_ms"].to_numpy(dtype=float)
        service_err = out.loc[pos, "error_rate"].to_numpy(dtype=float)

        # (t, t+H] -> start at i+1, include samples with ts <= t+H.
        ends = times + horizon
        stops = np.searchsorted(times, ends, side="right")
        for i, row_pos in enumerate(pos):
            start = i + 1
            stop = int(stops[i])
            if stop <= start:
                continue
            window_major = service_major[start:stop]
            window_times = times[start:stop]
            # Each observed sample owns the interval until the next sample (or
            # the horizon edge).  This keeps duration sensible on irregular
            # cadences and never counts the row at t itself.
            next_times = np.empty_like(window_times)
            next_times[:-1] = window_times[1:]
            next_times[-1] = ends[i]
            coverage = np.clip(next_times - window_times, 0.0, float(horizon))
            has_major = bool(window_major.any())
            y_major[row_pos] = has_major
            dur_est[row_pos] = min(float(horizon), float(coverage[window_major].sum()))
            valid[row_pos] = bool(ends[i] <= times[-1] + 1e-9)

            if use_taxonomy and has_major:
                max_p95 = float(np.nanmax(service_p95[start:stop]))
                max_err = float(np.nanmax(service_err[start:stop]))
                failure_mode[row_pos] = classify_failure_mode(max_p95, max_err, cfg)

    out["y_major"] = y_major
    out["dur_est_s"] = dur_est
    out["label_valid"] = valid
    if use_taxonomy:
        out["failure_mode"] = failure_mode
    return out
