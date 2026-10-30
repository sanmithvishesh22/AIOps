import os
import sys

import numpy as np
from sklearn.ensemble import IsolationForest

from ..ingest import sample_frame
from ..common import store


FEATURES = [
    "p95_ms",
    "error_rate",
    "cpu",
    "mem",
    "replicas",
    "rps",
]


def detect(frame, threshold=0.8):
    """Run a per-service Isolation Forest and return inference rows."""

    rows = []

    for service, group in frame.groupby("service"):
        work = group.copy()

        # Keep the original frame unchanged.
        # IsolationForest cannot consume missing numeric values.
        values = work[FEATURES].astype(float)
        values = values.fillna(values.median()).fillna(0.0)

        model = IsolationForest(
            random_state=42,
            contamination="auto",
        )
        model.fit(values)

        raw = model.score_samples(values)

        # Convert Isolation Forest's lower-is-more-anomalous score
        # into a normalized anomaly score in [0, 1].
        low = float(raw.min())
        high = float(raw.max())

        if high == low:
            scores = np.zeros(len(raw), dtype=float)
        else:
            scores = (high - raw) / (high - low)

        scores = np.clip(scores, 0.0, 1.0)

        for (_, row), score in zip(work.iterrows(), scores):
            score = float(score)
            flag = 1.0 if score >= threshold else 0.0

            meta = {
                "detector": "iforest",
                "threshold": threshold,
                "features": FEATURES,
            }

            rows.append(
                {
                    "ts": float(row["ts"]),
                    "module": "detect",
                    "service": service,
                    "kind": "anomaly_score",
                    "value": score,
                    "meta": meta,
                }
            )

            rows.append(
                {
                    "ts": float(row["ts"]),
                    "module": "detect",
                    "service": service,
                    "kind": "anomaly_flag",
                    "value": flag,
                    "meta": meta,
                }
            )

    return rows


def _selftest():
    frame = sample_frame()

    rows = detect(frame, threshold=0.8)

    assert rows, "detector returned no rows"

    scores = [
        row["value"]
        for row in rows
        if row["kind"] == "anomaly_score"
    ]
    flags = [
        row["value"]
        for row in rows
        if row["kind"] == "anomaly_flag"
    ]

    assert scores, "no anomaly_score rows"
    assert flags, "no anomaly_flag rows"

    assert all(0.0 <= value <= 1.0 for value in scores)
    assert all(value in (0.0, 1.0) for value in flags)

    # Verify the severity gate.
    for score, flag in zip(scores, flags):
        assert flag == (1.0 if score >= 0.8 else 0.0)

    # Verify rows satisfy the shared store contract.
    store.normalize(rows)

    # Inject an obvious outlier and verify that it is flagged.
    outlier = frame.iloc[0].copy()
    outlier["ts"] = float(outlier["ts"]) + 100.0
    outlier["p95_ms"] = 100000.0
    outlier["error_rate"] = 1.0
    outlier["cpu"] = 100.0
    outlier["mem"] = 100.0
    outlier["rps"] = 100000.0

    test_frame = __import__("pandas").concat(
        [frame, __import__("pandas").DataFrame([outlier])],
        ignore_index=True,
    )

    test_rows = detect(test_frame, threshold=0.8)

    outlier_flags = [
        row["value"]
        for row in test_rows
        if row["kind"] == "anomaly_flag"
        and row["ts"] == float(outlier["ts"])
    ]

    assert outlier_flags == [1.0], "injected outlier was not flagged"

    print("detect selftest OK")


def main():
    if "--selftest" in sys.argv:
        _selftest()
        return

    threshold = float(os.environ.get("ANOMALY_THRESHOLD", "0.8"))
    rows = detect(sample_frame(), threshold=threshold)
    store.write(rows)
    print(f"wrote {len(rows)} inference rows")


if __name__ == "__main__":
    main()