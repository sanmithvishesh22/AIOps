"""Offline-only CSV importer for the Contract C feature frame (D1-007).

Maps a local CSV file into the frozen feature-frame shape used by the ML modules.
This path is for offline model validation only, not reliability proof: it never
contacts Prometheus, TimescaleDB, Kubernetes, or any network service, and it is
not part of the production ingestion path.

Required CSV columns (any order):
    ts, service, p95_ms, error_rate, cpu, mem, replicas, rps

``ts`` accepts Unix epoch seconds or ISO-8601 timestamps; timezone-naive ISO-8601
values are treated as UTC. Only empty metric cells and literal ``NaN`` are treated
as missing; they stay NaN and are never filled.
Offline check: ``python -m aiops.ingest_csv --selftest``.
"""
from __future__ import annotations

import io
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
import pandas as pd

from .ingest import COLUMNS

LABEL = "offline model-validation only, not reliability proof"
_METRIC_COLUMNS = COLUMNS[2:]

_SAMPLE_CSV = """ts,service,p95_ms,error_rate,cpu,mem,replicas,rps
1700000015,front-end,180.2,,0.30,140000000,3,47.0
1700000000,orders,95.0,0.00,0.15,67108864,2,18.5
1700000000,front-end,120.5,0.01,0.25,134217728,3,42.0
1700000015,orders,NaN,0.02,,70000000,2,20.0
"""

_ISO_SAMPLE_CSV = """service,ts,rps,replicas,mem,cpu,error_rate,p95_ms
front-end,2026-10-29T00:00:15Z,47.0,3,140000000,0.30,,180.2
orders,2026-10-29T00:00:00,18.5,2,67108864,0.15,0.00,95.0
"""


def _validate_columns(columns) -> None:
    actual = list(columns)
    missing = [name for name in COLUMNS if name not in actual]
    extra = [name for name in actual if name not in COLUMNS]
    if missing or extra:
        raise ValueError(
            f"CSV columns must be exactly {COLUMNS}; "
            f"missing={missing}, extra={extra}"
        )


def _parse_ts(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.strip()
    missing = series.isna() | text.eq("") | text.str.lower().eq("nan")
    if missing.any():
        raise ValueError("ts: missing timestamps are not allowed")

    numeric = pd.to_numeric(text, errors="coerce")
    numeric_count = int(numeric.notna().sum())
    if numeric_count == len(series):
        ts = numeric.astype(float)
        if not np.isfinite(ts).all():
            raise ValueError("ts: timestamps must be finite Unix seconds")
        return ts

    if numeric_count:
        raise ValueError(
            "ts: mixed numeric and ISO-8601 timestamp formats are not allowed"
        )

    try:
        parsed = pd.to_datetime(
            text, utc=True, errors="raise", format="ISO8601"
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"ts: invalid ISO-8601 timestamp: {exc}") from exc
    if parsed.isna().any():
        raise ValueError("ts: missing timestamps are not allowed")

    epoch = pd.Timestamp("1970-01-01", tz="UTC")
    return (parsed - epoch) / pd.Timedelta(seconds=1)


def load_csv(path: str | Path) -> pd.DataFrame:
    """Load ``path`` as a Contract C feature frame.

    The CSV must contain exactly the eight Contract C columns in any order.
    Timestamps are returned as Unix seconds. Empty metric cells and literal
    ``NaN`` stay NaN; nothing is zero-filled, interpolated, forward-filled, or
    synthesized. The returned frame is sorted by ``(ts, service)`` with a reset
    index and carries the offline-only usage label in
    ``frame.attrs["usage_label"]``.
    """
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    _validate_columns(raw.columns)

    frame = raw.loc[:, COLUMNS].copy()
    frame["ts"] = _parse_ts(frame["ts"])

    service = frame["service"]
    if service.isna().any():
        raise ValueError("service: blank service names are not allowed")
    service = service.astype(str).str.strip()
    if (service == "").any():
        raise ValueError("service: blank service names are not allowed")
    frame["service"] = service

    for column in _METRIC_COLUMNS:
        values = frame[column].astype(str).str.strip()
        missing = values.eq("") | values.str.lower().eq("nan")
        values = values.mask(missing, np.nan)
        try:
            frame[column] = pd.to_numeric(values, errors="raise").astype(float)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{column}: invalid non-empty metric value: {exc}"
            ) from exc

    duplicates = frame.duplicated(subset=["ts", "service"], keep=False)
    if duplicates.any():
        first = frame.loc[duplicates, ["ts", "service"]].iloc[0]
        raise ValueError(
            "duplicate (ts, service) rows are not allowed: "
            f"ts={first['ts']!r}, service={first['service']!r}"
        )

    frame = frame.sort_values(["ts", "service"]).reset_index(drop=True)
    frame.attrs["usage_label"] = LABEL
    return frame


def _expect_value_error(call, expected: str, case: str) -> None:
    try:
        call()
    except ValueError as exc:
        message = str(exc)
        assert expected.lower() in message.lower(), (
            f"{case}: unexpected error: {message}"
        )
    else:
        raise AssertionError(f"{case}: expected ValueError")


def _selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        def write(name: str, text: str) -> Path:
            path = root / name
            path.write_text(text, encoding="utf-8")
            return path

        header = ",".join(COLUMNS)
        sample = write("sample.csv", _SAMPLE_CSV)
        frame = load_csv(sample)

        assert list(frame.columns) == COLUMNS, "canonical columns/order expected"
        assert list(frame["service"]) == [
            "front-end", "orders", "front-end", "orders"
        ], "rows must be sorted by (ts, service)"
        assert frame["ts"].tolist() == [
            1700000000.0, 1700000000.0, 1700000015.0, 1700000015.0
        ], "timestamps must be Unix seconds"
        assert frame.index.tolist() == [0, 1, 2, 3], "index must be reset"

        assert np.isnan(
            frame.loc[
                (frame["ts"] == 1700000015.0)
                & (frame["service"] == "front-end"),
                "error_rate",
            ].iloc[0]
        ), "empty metric cell must remain NaN"
        assert np.isnan(
            frame.loc[
                (frame["ts"] == 1700000015.0)
                & (frame["service"] == "orders"),
                "p95_ms",
            ].iloc[0]
        ), "literal NaN must remain NaN"
        assert np.isnan(
            frame.loc[
                (frame["ts"] == 1700000015.0)
                & (frame["service"] == "orders"),
                "cpu",
            ].iloc[0]
        ), "empty metric cell must not be zero-filled"
        assert frame.attrs["usage_label"] == LABEL, "usage label missing from attrs"

        output = io.StringIO()
        with redirect_stdout(output):
            main([str(sample)])
        assert output.getvalue().splitlines()[0] == LABEL, "CLI must print the label"

        iso = write("iso.csv", _ISO_SAMPLE_CSV)
        iso_frame = load_csv(iso)
        assert list(iso_frame.columns) == COLUMNS, "reordered headers must normalize"
        assert iso_frame["ts"].tolist() == [
            pd.Timestamp("2026-10-29T00:00:00", tz="UTC").timestamp(),
            pd.Timestamp("2026-10-29T00:00:15", tz="UTC").timestamp(),
        ], "ISO-8601 timestamps (including naive values) must be UTC Unix seconds"
        assert iso_frame["service"].tolist() == ["orders", "front-end"]

        empty = write("empty.csv", header + "\n")
        empty_frame = load_csv(empty)
        assert empty_frame.empty, "header-only CSV must not synthesize rows"
        assert list(empty_frame.columns) == COLUMNS

        missing = write(
            "missing.csv",
            "service,p95_ms,error_rate,cpu,mem,replicas,rps\n"
            "orders,1.0,0.01,0.1,1,2,3\n",
        )
        _expect_value_error(lambda: load_csv(missing), "missing", "missing header")

        extra = write(
            "extra.csv",
            header + ",note\n"
            "1700000000,orders,1.0,0.01,0.1,1,2,3,extra\n",
        )
        _expect_value_error(lambda: load_csv(extra), "extra", "extra header")

        case = write(
            "case.csv",
            "Ts,service,p95_ms,error_rate,cpu,mem,replicas,rps\n"
            "1700000000,orders,1.0,0.01,0.1,1,2,3\n",
        )
        _expect_value_error(lambda: load_csv(case), "Ts", "case-mismatched header")

        bad_metric = write(
            "bad_metric.csv",
            header + "\n1700000000,orders,high,0.01,0.1,1,2,3\n",
        )
        _expect_value_error(
            lambda: load_csv(bad_metric), "p95_ms", "invalid metric text"
        )

        na_metric = write(
            "na_metric.csv",
            header + "\n1700000000,orders,N/A,0.01,0.1,1,2,3\n",
        )
        _expect_value_error(
            lambda: load_csv(na_metric), "p95_ms", "unsupported NA token"
        )

        missing_ts = write(
            "missing_ts.csv",
            header + "\n,orders,1.0,0.01,0.1,1,2,3\n",
        )
        _expect_value_error(
            lambda: load_csv(missing_ts), "ts", "missing timestamp"
        )

        blank_service = write(
            "blank_service.csv",
            header + "\n1700000000,   ,1.0,0.01,0.1,1,2,3\n",
        )
        _expect_value_error(
            lambda: load_csv(blank_service), "service", "blank service"
        )

        duplicate = write(
            "duplicate.csv",
            header + "\n"
            "1700000000,orders,1.0,0.01,0.1,1,2,3\n"
            "1700000000,orders,2.0,0.02,0.2,2,3,4\n",
        )
        _expect_value_error(
            lambda: load_csv(duplicate), "duplicate", "duplicate key"
        )

        mixed_ts = write(
            "mixed_ts.csv",
            header + "\n"
            "1700000000,orders,1.0,0.01,0.1,1,2,3\n"
            "2026-10-29T00:00:15Z,catalogue,2.0,0.02,0.2,2,3,4\n",
        )
        _expect_value_error(
            lambda: load_csv(mixed_ts), "mixed", "mixed timestamp formats"
        )

    print("ingest_csv selftest OK")


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--selftest"]:
        _selftest()
        return
    if len(args) != 1:
        raise SystemExit(
            "usage: python -m aiops.ingest_csv <file.csv> | "
            "python -m aiops.ingest_csv --selftest"
        )

    frame = load_csv(args[0])
    print(LABEL)
    print(frame.to_string(index=False))


if __name__ == "__main__":
    main()
