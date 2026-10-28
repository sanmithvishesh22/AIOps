"""Leakage-safe feature engineering for the D3-001 breach predictor.

Contract C gives one row per ``(ts, service)`` with six metrics.  This module
derives per-service trailing features only: at time ``t`` a feature may use rows
with timestamp ``<= t`` and never a later row.  Services are grouped before any
shift/rolling operation, so one service's data cannot bleed into another's.

NaN policy (Contract C / PS-6): gaps stay NaN.  We never zero-fill; the model's
imputer handles missing cells explicitly.
"""
from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np
import pandas as pd

BASE_COLUMNS = ["p95_ms", "error_rate", "cpu", "mem", "replicas", "rps"]
KEY_COLUMNS = ["ts", "service"]

LAGS = (1, 2, 4)
ROLL_WINDOWS = (4, 8)
SLOPE_WINDOW = 4
SLOPE_COLUMNS = ("p95_ms", "error_rate", "cpu", "mem", "rps")
DELTA_COLUMNS = ("p95_ms", "error_rate", "cpu", "mem", "rps")


def _feature_names() -> list[str]:
    """Stable feature order — changing this changes the persisted artifact schema."""
    cols: list[str] = []
    for col in BASE_COLUMNS:
        cols.append(col)
        cols.extend(f"{col}_lag{lag}" for lag in LAGS)
        cols.extend(f"{col}_mean{window}" for window in ROLL_WINDOWS)
        cols.append(f"{col}_std4")
        if col in SLOPE_COLUMNS:
            cols.append(f"{col}_slope{SLOPE_WINDOW}")
        if col in DELTA_COLUMNS:
            cols.append(f"{col}_delta1")
    return cols


FEATURE_COLUMNS = _feature_names()


def _empty_features() -> pd.DataFrame:
    data: dict[str, pd.Series] = {
        "ts": pd.Series(dtype="float64"),
        "service": pd.Series(dtype="object"),
    }
    for col in FEATURE_COLUMNS:
        data[col] = pd.Series(dtype="float64")
    return pd.DataFrame(data)


def _slope(values: np.ndarray) -> float:
    """Least-squares slope over the finite points in a trailing window."""
    y = np.asarray(values, dtype=float)
    mask = np.isfinite(y)
    if mask.sum() < 2:
        return np.nan
    x = np.arange(len(y), dtype=float)[mask]
    return float(np.polyfit(x, y[mask], 1)[0])


def _validate_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None:
        raise ValueError("feature frame is None")
    missing = [c for c in KEY_COLUMNS + BASE_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"feature frame missing columns: {missing}")
    work = frame[KEY_COLUMNS + BASE_COLUMNS].copy()
    if work.empty:
        return work
    work["ts"] = pd.to_numeric(work["ts"], errors="raise").astype(float)
    if not np.isfinite(work["ts"]).all():
        raise ValueError("feature frame contains non-finite timestamps")
    if work["service"].isna().any():
        raise ValueError("feature frame contains null service labels")
    work["service"] = work["service"].astype(str)
    if work.duplicated(KEY_COLUMNS).any():
        dup = work.loc[work.duplicated(KEY_COLUMNS, keep=False), KEY_COLUMNS].head(3)
        raise ValueError(f"duplicate (ts, service) rows: {dup.to_dict('records')}")
    for col in BASE_COLUMNS:
        work[col] = (
            pd.to_numeric(work[col], errors="coerce")
            .astype(float)
            .replace([np.inf, -np.inf], np.nan)
        )
    return work


def build_features(
    frame: pd.DataFrame,
    feature_cols: Sequence[str] | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Return ``(features, feature_cols)`` for a Contract-C frame.

    The returned frame carries ``ts``/``service`` plus every column in
    ``feature_cols`` (default :data:`FEATURE_COLUMNS`), sorted by
    ``(ts, service)``.  Early rows naturally contain NaNs for trailing features;
    that is intentional (the model imputes them).
    """
    work = _validate_frame(frame)
    cols = list(FEATURE_COLUMNS if feature_cols is None else feature_cols)
    unknown = [c for c in cols if c not in FEATURE_COLUMNS]
    if unknown:
        raise ValueError(f"unknown feature columns: {unknown}")
    if work.empty:
        empty = _empty_features()
        return empty[KEY_COLUMNS + cols], cols

    parts: list[pd.DataFrame] = []
    for _, group in work.groupby("service", sort=True):
        g = group.sort_values("ts", kind="mergesort")
        out = g[KEY_COLUMNS + BASE_COLUMNS].copy()
        for col in BASE_COLUMNS:
            series = g[col].astype(float)
            out[f"{col}_lag1"] = series.shift(1)
            out[f"{col}_lag2"] = series.shift(2)
            out[f"{col}_lag4"] = series.shift(4)
            out[f"{col}_mean4"] = series.rolling(4, min_periods=4).mean()
            out[f"{col}_mean8"] = series.rolling(8, min_periods=8).mean()
            out[f"{col}_std4"] = series.rolling(4, min_periods=4).std()
            if col in SLOPE_COLUMNS:
                out[f"{col}_slope{SLOPE_WINDOW}"] = series.rolling(
                    SLOPE_WINDOW, min_periods=SLOPE_WINDOW
                ).apply(_slope, raw=True)
            if col in DELTA_COLUMNS:
                out[f"{col}_delta1"] = series.diff()
        parts.append(out)

    result = (
        pd.concat(parts, ignore_index=True)
        .sort_values(KEY_COLUMNS, kind="mergesort")
        .reset_index(drop=True)
    )
    return result[KEY_COLUMNS + cols], cols


def future_rows_unchanged(
    frame: pd.DataFrame,
    changed: pd.DataFrame,
    cutoff_ts: float,
    feature_cols: Iterable[str] | None = None,
    tolerance: float = 1e-9,
) -> bool:
    """Test helper: every feature at ``ts <= cutoff_ts`` is identical in both frames.

    Used by the offline leakage probe (TS-3): perturbing a later row must not
    change any earlier row's features.  Returns True when the test passes.
    """
    cols = list(feature_cols or FEATURE_COLUMNS)
    left, left_cols = build_features(frame, cols)

    right, right_cols = build_features(changed, cols)
    left = left[left["ts"] <= cutoff_ts].set_index(KEY_COLUMNS).sort_index()
    right = right[right["ts"] <= cutoff_ts].set_index(KEY_COLUMNS).sort_index()
    if not left.index.equals(right.index):
        return False
    a = left[left_cols].to_numpy(dtype=float)
    b = right[right_cols].to_numpy(dtype=float)
    return bool(np.allclose(a, b, rtol=tolerance, atol=tolerance, equal_nan=True))
