import sys

import numpy as np
import pandas as pd
import torch
from torch import nn

from ..common import store
from ..ingest import sample_frame


FEATURES = [
    "p95_ms",
    "error_rate",
    "cpu",
    "mem",
    "replicas",
    "rps",
]

WINDOW_SIZE = 2
HIDDEN_SIZE = 8
EPOCHS = 80
LEARNING_RATE = 0.01


class LSTMAutoencoder(nn.Module):
    def __init__(self, input_size, hidden_size=HIDDEN_SIZE):
        super().__init__()

        self.encoder = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            batch_first=True,
        )

        self.decoder = nn.LSTM(
            input_size=hidden_size,
            hidden_size=input_size,
            batch_first=True,
        )

    def forward(self, x):
        _, (hidden, _) = self.encoder(x)

        repeated = hidden[-1].unsqueeze(1).repeat(
            1, x.size(1), 1
        )

        output, _ = self.decoder(repeated)

        return output


def _prepare_features(frame):
    values = frame[FEATURES].astype(float)
    values = values.fillna(values.median()).fillna(0.0)

    return values.to_numpy(dtype=np.float32)


def _make_windows(values, window_size=WINDOW_SIZE):
    if len(values) < window_size:
        return np.empty(
            (0, window_size, len(FEATURES)),
            dtype=np.float32,
        )

    return np.stack(
        [
            values[index:index + window_size]
            for index in range(len(values) - window_size + 1)
        ]
    )


def _scale(values):
    minimum = values.min(axis=0)
    maximum = values.max(axis=0)

    span = maximum - minimum
    span[span == 0] = 1.0

    scaled = (values - minimum) / span

    return scaled.astype(np.float32), minimum, span


def _train_model(windows):
    torch.manual_seed(42)

    model = LSTMAutoencoder(len(FEATURES))
    optimizer = torch.optim.Adam(
        model.parameters(),
        lr=LEARNING_RATE,
    )
    loss_fn = nn.MSELoss()

    x = torch.tensor(windows, dtype=torch.float32)

    model.train()

    for _ in range(EPOCHS):
        optimizer.zero_grad()

        reconstructed = model(x)
        loss = loss_fn(reconstructed, x)

        loss.backward()
        optimizer.step()

    return model


def reconstruction_errors(model, windows):
    if len(windows) == 0:
        return np.array([], dtype=float)

    model.eval()

    with torch.no_grad():
        x = torch.tensor(windows, dtype=torch.float32)
        reconstructed = model(x)

        errors = torch.mean(
            (reconstructed - x) ** 2,
            dim=(1, 2),
        )

    return errors.numpy()


def score_frame(frame):
    rows = []

    for service, group in frame.groupby("service"):
        group = group.sort_values("ts").reset_index(drop=True)

        values = _prepare_features(group)

        scaled, minimum, span = _scale(values)

        windows = _make_windows(scaled)

        if len(windows) == 0:
            continue

        model = _train_model(windows)

        errors = reconstruction_errors(model, windows)

        for index, error in enumerate(errors):
            end_index = index + WINDOW_SIZE - 1

            rows.append(
                {
                    "ts": float(group.iloc[end_index]["ts"]),
                    "module": "detect",
                    "service": service,
                    "kind": "anomaly_score_seq",
                    "value": float(error),
                    "meta": {
                        "detector": "lstm_autoencoder",
                        "window": WINDOW_SIZE,
                        "features": FEATURES,
                    },
                }
            )

    return rows


def _selftest():
    frame = sample_frame()

    rows = score_frame(frame)

    assert rows, "no sequence scores produced"

    assert all(
        row["kind"] == "anomaly_score_seq"
        for row in rows
    )

    store.normalize(rows)

    # Train on the clean fixture.
    service = frame["service"].iloc[0]
    clean = (
        frame[frame["service"] == service]
        .sort_values("ts")
        .reset_index(drop=True)
    )

    clean_values = _prepare_features(clean)
    clean_scaled, minimum, span = _scale(clean_values)

    clean_windows = _make_windows(clean_scaled)

    model = _train_model(clean_windows)

    clean_errors = reconstruction_errors(
        model,
        clean_windows,
    )

    # Add an obvious anomalous point after training.
    anomaly = clean.iloc[-1].copy()
    anomaly["p95_ms"] = 100000.0
    anomaly["error_rate"] = 1.0
    anomaly["cpu"] = 100.0
    anomaly["mem"] = 100.0
    anomaly["rps"] = 100000.0

    anomaly_values = _prepare_features(
        pd.concat(
            [clean.iloc[:-1], pd.DataFrame([anomaly])],
            ignore_index=True,
        )
    )

    anomaly_scaled = (
        anomaly_values - minimum
    ) / span

    anomaly_window = _make_windows(anomaly_scaled)[-1:]

    anomaly_error = reconstruction_errors(
        model,
        anomaly_window,
    )[0]

    assert anomaly_error > float(clean_errors.mean()), (
        "anomalous window did not have higher reconstruction error"
    )

    print("lstm_autoencoder selftest OK")


def main():
    if "--selftest" in sys.argv:
        _selftest()
        return

    rows = score_frame(sample_frame())
    store.write(rows)

    print(f"wrote {len(rows)} sequence inference rows")


if __name__ == "__main__":
    main()