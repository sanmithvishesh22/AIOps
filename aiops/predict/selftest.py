"""Offline assert-based check for D3-001 (no cluster, network, or database).

The fixture here is synthetic and explicitly mechanics-only (TS-6): it proves
the pipeline, guards and contracts work, never that the model or platform has a
certain predictive quality.  Real scoring stays invalid until D3-000.7 freezes
the calibration-locked anchors.
"""
from __future__ import annotations

import os
import tempfile
from typing import Callable

import numpy as np
import pandas as pd

from ..common import store
from . import config
from .features import FEATURE_COLUMNS, build_features, future_rows_unchanged
from .inference import inference_rows, write_inference
from .labels import label_frame, severity_masks
from .metrics import pr_auc, precision_recall_at, select_threshold
from .model import BreachPredictor
from .pipeline import fit_production_predictor, prepare_dataset, run_pipeline
from .split import (
    assert_no_infected,
    chrono_split,
    exclude_infected,
)

START = 1_700_000_000.0
STEP = 15.0


def _assert_raises(exc: type[BaseException], fn: Callable[[], object], text: str | None = None) -> None:
    try:
        fn()
    except exc as err:
        if text is not None and text.lower() not in str(err).lower():
            raise AssertionError(f"{exc.__name__} message missing {text!r}: {err}") from err
    else:
        raise AssertionError(f"expected {exc.__name__}")


def synthetic_frame(
    n: int = 240,
    seed: int = 7,
    services: tuple[str, ...] = ("front-end", "catalogue"),
) -> pd.DataFrame:
    """Seeded Contract-C-shaped frame with periodic SLO breaches and NaN gaps."""
    from ..ingest import COLUMNS

    rng = np.random.default_rng(seed)
    frames = []
    for offset, service in enumerate(services):
        i = np.arange(n, dtype=float)
        wave = np.sin(2.0 * np.pi * i / 80.0 + 0.9 * offset)
        p95 = 250.0 + 20.0 * offset + 220.0 * wave + rng.normal(0.0, 5.0, n)
        error_rate = np.clip(
            0.002 + 0.004 * np.maximum(wave, 0.0) + rng.normal(0.0, 0.0003, n),
            0.0,
            0.009,
        )
        cpu = np.clip(0.45 + 0.25 * wave + rng.normal(0.0, 0.015, n), 0.0, 1.0)
        mem = np.clip(0.55 + 0.08 * wave + rng.normal(0.0, 0.01, n), 0.0, 1.0)
        replicas = np.clip(2.0 + np.floor(3.0 * np.maximum(wave, 0.0)), 2, 6)
        rps = np.clip(120.0 + 100.0 * wave + rng.normal(0.0, 4.0, n), 10.0, None)
        ts = START + i * STEP

        # Keep the Contract-C NaN policy visible in the fixture.
        if service == "front-end":
            cpu[120] = np.nan
        else:
            error_rate[50] = np.nan
        frames.append(
            pd.DataFrame(
                {
                    "ts": ts,
                    "service": service,
                    "p95_ms": p95,
                    "error_rate": error_rate,
                    "cpu": cpu,
                    "mem": mem,
                    "replicas": replicas,
                    "rps": rps,
                }
            )
        )
    frame = pd.concat(frames, ignore_index=True)
    return (
        frame.sort_values(["ts", "service"], kind="mergesort")
        .reset_index(drop=True)[COLUMNS]
    )


# --------------------------------------------------------------------- features
def _test_features(frame: pd.DataFrame) -> None:
    feats, cols = build_features(frame)
    assert cols == FEATURE_COLUMNS, "feature list must be stable and ordered"
    assert list(feats.columns) == ["ts", "service"] + FEATURE_COLUMNS
    assert len(feats) == len(frame), "one feature row per input row"
    order = feats[["ts", "service"]].to_numpy(dtype=object).tolist()
    assert order == sorted(order, key=lambda row: (float(row[0]), str(row[1]))), "sorted"

    gap_ts = START + 120 * STEP
    gap = feats[(feats.service == "front-end") & (feats.ts == gap_ts)]["cpu"].iloc[0]
    assert np.isnan(gap), "Contract-C NaN gap must survive feature engineering"

    # A service's future cannot bleed into another service's features.
    altered = frame.copy()
    mask = (altered.service == "catalogue") & (altered.ts == START + 26.0 * STEP)
    assert mask.any(), "fixture row for cross-service probe must exist"
    altered.loc[mask, "p95_ms"] += 999.0
    a, _ = build_features(frame)
    b, _ = build_features(altered)
    fa = a[a.service == "front-end"].reset_index(drop=True)
    fb = b[b.service == "front-end"].reset_index(drop=True)
    assert np.allclose(
        fa[FEATURE_COLUMNS].to_numpy(float),
        fb[FEATURE_COLUMNS].to_numpy(float),
        equal_nan=True,
    ), "cross-service feature bleed"

    # TS-3 leakage probe: a changed future row must not change any earlier row.
    last_ts = float(frame[frame.service == "front-end"].ts.max())
    future = frame.copy()
    last_mask = (future.service == "front-end") & (future.ts == last_ts)
    assert last_mask.any(), "fixture must contain the latest front-end row"
    future.loc[last_mask, "p95_ms"] += 1000.0
    assert future_rows_unchanged(frame, future, last_ts - 0.5), "future leakage"

    duplicate = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    _assert_raises(ValueError, lambda: build_features(duplicate), "duplicate")

    empty, empty_cols = build_features(frame.iloc[0:0])
    assert empty.empty and empty_cols == FEATURE_COLUMNS
    assert list(empty.columns) == ["ts", "service"] + FEATURE_COLUMNS

    single = frame.iloc[[0]].copy()
    single["service"] = "solo"
    solo, _ = build_features(single)
    assert len(solo) == 1
    assert np.isfinite(solo.loc[0, "p95_ms"]), "current metric must survive"
    assert np.isnan(solo.loc[0, "p95_ms_lag1"]), "single row has no lag"


# ------------------------------------------------------------------------ labels
def _label_fixture(
    n: int = 20,
    p95: np.ndarray | None = None,
    error: np.ndarray | None = None,
) -> pd.DataFrame:
    ts = START + np.arange(n, dtype=float) * STEP
    if p95 is None:
        p95 = np.full(n, 100.0)
    if error is None:
        error = np.full(n, 0.001)
    return pd.DataFrame(
        {
            "ts": ts,
            "service": "svc",
            "p95_ms": p95,
            "error_rate": error,
            "cpu": np.full(n, 0.4),
            "mem": np.full(n, 0.5),
            "replicas": np.full(n, 2.0),
            "rps": np.full(n, 100.0),
        }
    )


def _test_labels() -> None:
    p95 = np.full(20, 100.0)
    p95[4:7] = 600.0  # t = 60, 75, 90 s
    frame = _label_fixture(p95=p95)
    lab = label_frame(frame, horizon_s=120, slo_p95_ms=300, major_p95_ms=450, slo_error_rate=0.01)

    assert bool(lab.loc[0, "y_major"]), "window (0, 120] contains the breach"
    assert float(lab.loc[0, "dur_est_s"]) == 45.0, "three 15 s major samples"
    assert bool(lab.loc[3, "y_major"]), "window (45, 165] contains the breach"
    assert float(lab.loc[3, "dur_est_s"]) == 45.0
    assert not bool(lab.loc[6, "y_major"]), "row at t must not label itself"
    assert float(lab.loc[6, "dur_est_s"]) == 0.0
    assert bool(lab.loc[5, "y_major"]), "next rows are still forward-labelled"
    assert float(lab.loc[5, "dur_est_s"]) == 15.0
    assert bool(lab.loc[11, "label_valid"]), "full horizon observed through t=165"
    assert not bool(lab.loc[12, "label_valid"]), "t=180 has no full forward window"

    # An own-row breach never labels itself.
    only_own = np.full(20, 100.0)
    only_own[6] = 900.0
    own_lab = label_frame(
        _label_fixture(p95=only_own),
        horizon_s=120,
        slo_p95_ms=300,
        major_p95_ms=450,
        slo_error_rate=0.01,
    )
    assert not bool(own_lab.loc[6, "y_major"]), "strictly forward label window"
    assert bool(own_lab.loc[5, "y_major"]), "preceding row sees the future breach"

    # Error-rate breach follows the same forward-only rule.
    error = np.full(20, 0.001)
    error[10] = 0.02  # t = 150 s
    err_lab = label_frame(
        _label_fixture(error=error),
        horizon_s=120,
        slo_p95_ms=300,
        major_p95_ms=450,
        slo_error_rate=0.01,
    )
    assert bool(err_lab.loc[9, "y_major"]), "error breach within H"
    assert not bool(err_lab.loc[10, "y_major"]), "own error window excluded"

    # NaN metrics grade as non-breaches, never fabricated.
    nan_frame = _label_fixture()
    nan_frame.loc[15, "p95_ms"] = np.nan
    nan_frame.loc[15, "error_rate"] = np.nan
    major, minor = severity_masks(nan_frame)
    assert not bool(major.iloc[15]) and not bool(minor.iloc[15]), "NaN is not a breach"
    nan_lab = label_frame(
        nan_frame,
        horizon_s=120,
        slo_p95_ms=300,
        major_p95_ms=450,
        slo_error_rate=0.01,
    )
    assert not bool(nan_lab.loc[14, "y_major"]), "NaN future cannot trigger a label"

    # D3-009: Per-service failure-mode taxonomy selftest + no-regression check
    # 1. When taxonomy is enabled:
    tax_lab = label_frame(
        frame,
        horizon_s=120,
        slo_p95_ms=300,
        major_p95_ms=450,
        slo_error_rate=0.01,
        enable_taxonomy=True,
    )
    assert "failure_mode" in tax_lab.columns, "D3-009: failure_mode column must be present when enabled"
    assert tax_lab.loc[0, "failure_mode"] == "latency_breach"
    assert tax_lab.loc[6, "failure_mode"] == "none"

    # 2. When taxonomy is disabled (default): byte-identical no-regression check
    notax_lab = label_frame(
        frame,
        horizon_s=120,
        slo_p95_ms=300,
        major_p95_ms=450,
        slo_error_rate=0.01,
        enable_taxonomy=False,
    )
    assert "failure_mode" not in notax_lab.columns
    pd.testing.assert_frame_equal(lab, notax_lab)

    duplicate = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    _assert_raises(
        ValueError,
        lambda: label_frame(duplicate, horizon_s=120),
        "duplicate",
    )

    one = label_frame(_label_fixture(n=1), horizon_s=120)
    assert len(one) == 1 and not bool(one.loc[0, "label_valid"]), "single row handled"


# ------------------------------------------------------------------------- split
def _toy_split_frame(n: int = 120) -> pd.DataFrame:
    frames = []
    for service in ("a", "b"):
        ts = START + np.arange(n, dtype=float) * STEP
        frames.append(
            pd.DataFrame(
                {
                    "ts": ts,
                    "service": service,
                    "p95_ms": np.full(n, 100.0),
                    "error_rate": np.full(n, 0.001),
                }
            )
        )
    return pd.concat(frames, ignore_index=True).sort_values(
        ["ts", "service"], kind="mergesort"
    ).reset_index(drop=True)


def _test_split() -> None:
    frame = _toy_split_frame()
    split = chrono_split(frame, train_frac=2.0 / 3.0, horizon_s=120)
    assert split.train.ts.max() + 120.0 < split.test.ts.min(), "H embargo failed"
    assert split.train.ts.is_monotonic_increasing and split.test.ts.is_monotonic_increasing
    assert set(split.train.ts).isdisjoint(set(split.test.ts)), "shared timestamp leaked"
    assert any(np.isclose(split.test.ts, split.cut_ts)), "cut timestamp belongs to test"
    # All services at the cut move together.
    at_cut = frame[np.isclose(frame.ts, split.cut_ts)]
    assert set(at_cut.service) == {"a", "b"}
    assert set(at_cut.service) <= set(split.test.service)

    _assert_raises(ValueError, lambda: chrono_split(frame, train_frac=1.5), "train_frac")
    _assert_raises(ValueError, lambda: chrono_split(frame.iloc[0:2]), "two distinct")

    window = (START + 300.0, START + 450.0)
    clean = exclude_infected(split.train, [window], horizon_s=120)
    assert len(clean) < len(split.train), "infected rows were not removed"
    assert_no_infected(clean, [window], horizon_s=120)
    remaining = clean.ts.to_numpy(float)
    assert not np.any((remaining >= window[0]) & (remaining <= window[1]))
    assert not np.any((remaining + 120.0 >= window[0]) & (remaining <= window[1]))

    own_only = exclude_infected(frame, [window], horizon_s=0)
    assert not np.any(
        (own_only.ts.to_numpy(float) >= window[0])
        & (own_only.ts.to_numpy(float) <= window[1])
    )

    _assert_raises(
        ValueError,
        lambda: exclude_infected(frame, [(window[1], window[0])]),
        "start > end",
    )


# ----------------------------------------------------------------------- metrics
def _test_metrics() -> None:
    y = np.array([0, 0, 1, 1])
    s = np.array([0.1, 0.2, 0.8, 0.9])
    assert pr_auc(y, s) == 1.0, "perfect separation must score 1.0"
    precision, recall = precision_recall_at(y, s, 0.8)
    assert precision == 1.0 and recall == 1.0
    threshold, met = select_threshold(y, s, 0.7)
    assert met and 0.8 - 1e-12 <= threshold <= 0.8 + 1e-12, "threshold must meet target"
    assert select_threshold(y, s, 0.7) == (threshold, met), "deterministic"

    assert np.isnan(pr_auc([0, 0, 0], [0.1, 0.2, 0.3])), "no positives -> NaN"
    assert pr_auc([1, 1], [0.1, 0.2]) == 1.0, "all positives -> 1.0"
    assert np.isfinite(pr_auc([1, 0, 1, 0], [0.5, 0.5, 0.5, 0.5])), "ties handled"
    assert precision_recall_at(y, s, 2.0) == (0.0, 0.0), "no predictions -> 0/0"

    threshold, met = select_threshold([1, 0, 1, 0], [0.6, 0.7, 0.8, 0.9], 0.7)
    assert not met, "unreachable target must be reported, not silently met"
    assert 0.0 <= threshold <= 1.0
    _assert_raises(
        ValueError,
        lambda: select_threshold([0, 0], [0.1, 0.2], 0.7),
        "positive",
    )


# ------------------------------------------------------------------------- model
def _test_model(frame: pd.DataFrame) -> BreachPredictor:
    data, fcols = prepare_dataset(frame, horizon_s=120)
    split = chrono_split(data, train_frac=2.0 / 3.0, horizon_s=120)
    window = (START + 900.0, START + 1100.0)
    train = exclude_infected(split.train, [window], horizon_s=120)
    assert_no_infected(train, [window], horizon_s=120)
    assert set(train.y_major.astype(int)) == {0, 1}
    assert set(split.test.y_major.astype(int)) == {0, 1}

    model = BreachPredictor(
        feature_cols=fcols, horizon_s=120, seed=42, target_precision=0.70
    ).fit(train)
    assert model.threshold is not None and 0.0 <= model.threshold <= 1.0
    assert isinstance(model.target_met, bool)
    assert model.metadata["feature_cols"] == fcols
    assert model.metadata["provisional"] is True

    # Threshold provenance: it must equal the train-only selection, never a
    # threshold re-selected on the holdout.
    train_scores = model.classifier.predict_proba(model._matrix(train))[:, 1]
    expected_threshold, expected_met = select_threshold(
        train.y_major.astype(int), train_scores, 0.70
    )
    assert model.threshold == expected_threshold
    assert model.target_met == expected_met

    scored = model.predict(split.test)
    assert len(scored) == len(split.test)
    assert np.isfinite(scored.breach_prob.to_numpy(float)).all()
    assert ((scored.breach_prob >= 0.0) & (scored.breach_prob <= 1.0)).all()
    assert ((scored.breach_duration_est >= 0.0) & (scored.breach_duration_est <= 120.0)).all()
    assert scored.breach_flag.dtype == bool

    # PS-2 determinism under a fixed seed.
    again = BreachPredictor(
        feature_cols=fcols, horizon_s=120, seed=42, target_precision=0.70
    ).fit(train)
    assert np.allclose(
        scored.breach_prob.to_numpy(float),
        again.predict(split.test).breach_prob.to_numpy(float),
    ), "fixed seed must reproduce predictions"

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "predictor.joblib")
        model.save(path)
        loaded = BreachPredictor.load(path)
        assert np.allclose(
            scored.breach_prob.to_numpy(float),
            loaded.predict(split.test).breach_prob.to_numpy(float),
        ), "save/load must preserve predictions"

        import joblib

        payload = joblib.load(path)
        payload["feature_cols"] = fcols[:-1]
        joblib.dump(payload, path)
        _assert_raises(ValueError, lambda: BreachPredictor.load(path), "stale")

    single = train.copy()
    single["y_major"] = False
    _assert_raises(
        ValueError,
        lambda: BreachPredictor(feature_cols=fcols).fit(single),
        "single class",
    )
    _assert_raises(
        ValueError,
        lambda: model.predict(split.test.drop(columns=[fcols[0]])),
        "missing feature",
    )
    _assert_raises(RuntimeError, lambda: BreachPredictor().predict(split.test), "fitted")

    # Integration test for the estimator seam without depending on sklearn
    # internals: patch _build with the same fit/predict interface.
    class _FakeClassifier:
        def fit(self, X, y):
            return self

        def predict_proba(self, X):
            p = np.linspace(0.1, 0.9, len(X))
            return np.column_stack([1.0 - p, p])

    class _FakeRegressor:
        def fit(self, X, y):
            return self

        def predict(self, X):
            return np.full(len(X), 30.0)

    tiny = pd.DataFrame({col: np.arange(4, dtype=float) for col in fcols})
    tiny["ts"] = START + np.arange(4) * STEP
    tiny["service"] = "svc"
    tiny["y_major"] = [0, 0, 1, 1]
    tiny["dur_est_s"] = [0.0, 0.0, 15.0, 45.0]
    original_build = BreachPredictor._build
    BreachPredictor._build = lambda self: (_FakeClassifier(), _FakeRegressor())
    try:
        fake = BreachPredictor(feature_cols=fcols, horizon_s=120, seed=1).fit(tiny)
        fake_out = fake.predict(tiny)
        assert len(fake_out) == 4
        assert np.all(fake_out.breach_duration_est == 30.0)
    finally:
        BreachPredictor._build = original_build

    return model


# --------------------------------------------------------------------- inference
def _test_inference(model: BreachPredictor, test: pd.DataFrame) -> None:
    sample = test.head(5).copy()
    rows = inference_rows(model, sample)
    assert len(rows) == 2 * len(sample), "two Contract-A rows per input row"
    assert {r["kind"] for r in rows} == {"breach_prob", "breach_duration_est"}
    assert {r["module"] for r in rows} == {"predict"}
    assert all(r["meta"]["horizon_s"] == 120 for r in rows)
    assert all(0.0 <= float(r["meta"]["threshold"]) <= 1.0 for r in rows)

    normalized = store.normalize(rows)
    assert len(normalized) == len(rows), "rows must satisfy store.normalize"
    assert store.normalize(rows) == normalized, "replay must be deterministic"

    for row in rows:
        value = float(row["value"])
        if row["kind"] == "breach_prob":
            assert 0.0 <= value <= 1.0
        else:
            assert 0.0 <= value <= 120.0

    overridden = inference_rows(model, sample, ts=123.0)
    assert all(row["ts"] == 123.0 for row in overridden)
    assert inference_rows(model, sample.iloc[0:0]) == []

    captured: dict[str, object] = {}
    original_write = store.write

    def _capture(written):
        captured["rows"] = written
        return len(written)

    store.write = _capture
    try:
        count = write_inference(model, sample)
    finally:
        store.write = original_write
    assert count == 10 and captured["rows"] == rows, "write path must pass rows to store"


# ---------------------------------------------------------------------- pipeline
def _test_pipeline(frame: pd.DataFrame) -> None:
    window = (START + 900.0, START + 1100.0)
    result = run_pipeline(
        frame,
        train_frac=2.0 / 3.0,
        infected_windows=[window],
        seed=42,
        target_precision=0.70,
    )
    m = result.metrics
    assert np.isfinite(m["pr_auc"]), "PR-AUC must be computed"
    assert 0.0 <= m["pr_auc"] <= 1.0
    assert m["pr_auc"] > 0.5, "seeded mechanics fixture should be learnable"
    assert 0.0 <= m["holdout_precision"] <= 1.0
    assert 0.0 <= m["holdout_recall"] <= 1.0
    assert isinstance(m["threshold_target_met"], bool)
    assert m["provisional"] is True, "scored output must be labelled provisional"
    assert m["infected_rows_excluded"] > 0
    assert m["test_rows"] == len(result.test) == len(result.predictions)
    assert result.test.ts.min() > result.train.ts.max() + result.horizon_s
    assert_no_infected(result.train, [window], result.horizon_s)
    assert set(result.train.y_major.astype(int)) == {0, 1}
    assert set(result.test.y_major.astype(int)) == {0, 1}

    production = fit_production_predictor(
        frame, seed=42, target_precision=0.70, infected_windows=[window]
    )
    features, _ = build_features(frame, production.feature_cols)
    latest_keys = (
        frame.sort_values(["service", "ts"], kind="mergesort")
        .groupby("service", as_index=False)
        .tail(1)[["ts", "service"]]
    )
    latest = features.merge(latest_keys, on=["ts", "service"], validate="one_to_one")
    scored = production.predict(latest)
    assert len(scored) == 2 and np.isfinite(scored.breach_prob).all()


def run_selftest() -> None:
    frame = synthetic_frame()
    assert list(frame.columns) == [
        "ts",
        "service",
        "p95_ms",
        "error_rate",
        "cpu",
        "mem",
        "replicas",
        "rps",
    ]
    _test_features(frame)
    _test_labels()
    _test_split()
    _test_metrics()
    model = _test_model(frame)
    data, _ = prepare_dataset(frame, horizon_s=120)
    split = chrono_split(data, train_frac=2.0 / 3.0, horizon_s=120)
    _test_inference(model, split.test)
    _test_pipeline(frame)
    print(
        "predict selftest OK "
        f"(features={len(FEATURE_COLUMNS)}, H={config.HORIZON_S}s, "
        f"target_precision={config.TARGET_PRECISION})"
    )
