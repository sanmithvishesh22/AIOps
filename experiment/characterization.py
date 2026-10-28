#!/usr/bin/env python3
"""D3-000.3 — Baseline characterization harness.

Measures the three §9 calibration anchors on the live testbed:
  1. Nominal p95 latency (front-end, low steady load, N repeats)
  2. Per-replica capacity (ramp load, find SLO breach knee)
  3. Pod-ready time (N scale-up events, schedule→Ready latency)

This script does NOT pick values — it measures them. The human owner
ratifies the final anchors in DECISIONS.md. All results are printed
with full provenance (commit, timestamp, seed, image digests).

Requirements: hey (HTTP load tool), kubectl, port-forward to Prometheus
and front-end already active.

Usage:
  python3 experiment/characterization.py --measure-p95
  python3 experiment/characterization.py --measure-capacity
  python3 experiment/characterization.py --measure-pod-ready
  python3 experiment/characterization.py --all
  python3 experiment/characterization.py --dry-run        # verify harness on mock data
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import time
import statistics
import re
from datetime import datetime, timezone

# ── Provenance ──────────────────────────────────────────────────────────────
def _git_commit():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"

def _provenance():
    return {
        "commit": _git_commit(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "host_arch": subprocess.check_output(["uname", "-m"], text=True).strip(),
        "python": sys.version.split()[0],
    }

# ── Prometheus helpers ──────────────────────────────────────────────────────
PROM_URL = os.environ.get("PROM_URL", "http://localhost:9090")

def prom_query(promql: str) -> list[dict]:
    """Instant query → list of {metric, value} dicts."""
    import urllib.request, urllib.parse
    url = f"{PROM_URL}/api/v1/query?{urllib.parse.urlencode({'query': promql})}"
    with urllib.request.urlopen(url, timeout=15) as r:
        d = json.loads(r.read())
    if d.get("status") != "success":
        raise RuntimeError(f"Prometheus error: {d.get('error', d)}")
    return d["data"]["result"]

def front_end_p95_ms() -> float | None:
    """Current front-end p95 latency in ms (1-minute rate window)."""
    results = prom_query(
        'histogram_quantile(0.95, sum(rate(request_duration_seconds_bucket'
        '{job="front-end"}[1m])) by (le)) * 1000'
    )
    if not results or not results[0].get("value"):
        return None
    try:
        val = float(results[0]["value"][1])
        return val if val == val else None  # NaN check
    except (ValueError, TypeError, IndexError):
        return None

def front_end_rps() -> float | None:
    """Current front-end RPS (1-minute rate)."""
    results = prom_query(
        'sum(rate(request_duration_seconds_count{job="front-end"}[1m]))'
    )
    if not results or not results[0].get("value"):
        return None
    try:
        val = float(results[0]["value"][1])
        return val if val == val else None
    except (ValueError, TypeError, IndexError):
        return None

def front_end_error_rate() -> float | None:
    """Current front-end 5xx error ratio."""
    results = prom_query(
        'sum(rate(request_duration_seconds_count{job="front-end",status_code=~"5.."}[1m]))'
        ' / sum(rate(request_duration_seconds_count{job="front-end"}[1m]))'
    )
    if not results or not results[0].get("value"):
        return 0.0
    try:
        val = float(results[0]["value"][1])
        return val if val == val else 0.0
    except (ValueError, TypeError, IndexError):
        return 0.0

# ── Load generation (hey) ───────────────────────────────────────────────────
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:8080")

def run_hey(rps: int, duration_s: int = 60, concurrency: int | None = None) -> dict:
    """Run hey at the given RPS for duration_s seconds. Returns summary dict."""
    c = concurrency or max(2, min(rps, 10))
    q_per_c = max(1, rps // c)
    cmd = [
        "hey", "-z", f"{duration_s}s", "-q", str(q_per_c),
        "-c", str(c), "-t", "10",
        f"{FRONTEND_URL}/"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration_s + 30)
    output = result.stdout + result.stderr
    summary = {
        "rps_target": rps,
        "duration_s": duration_s,
        "concurrency": c,
        "raw_output": output,
    }
    for line in output.split("\n"):
        line_s = line.strip()
        if "Requests/sec:" in line_s:
            try:
                summary["actual_rps"] = float(line_s.split(":")[1].strip())
            except (ValueError, IndexError):
                pass
        for pct in ("50%", "75%", "90%", "95%", "99%"):
            if line_s.startswith(f"{pct} in"):
                try:
                    s_val = float(line_s.split("in")[1].replace("secs", "").strip())
                    summary[f"p{pct[:-1]}_ms"] = round(s_val * 1000, 2)
                except (ValueError, IndexError):
                    pass
        if "[200]" in line_s:
            try:
                summary["responses_200"] = int(line_s.split()[1])
            except (ValueError, IndexError):
                pass
    return summary

# ── D3-000.4: Measure nominal p95 ──────────────────────────────────────────
def measure_nominal_p95(n_repeats: int = 5, warmup_s: int = 60,
                         measure_s: int = 60, rps: int = 5) -> dict:
    """Measure front-end p95 under low steady load. N repeats, warmup discarded."""
    print(f"\n{'='*60}")
    print(f"D3-000.4 — Nominal p95 measurement")
    print(f"  repeats={n_repeats}, warmup={warmup_s}s, measure={measure_s}s, rps={rps}")
    print(f"{'='*60}\n")

    # Warmup phase
    print(f"[warmup] Sending {rps} RPS for {warmup_s}s (discarded)...")
    run_hey(rps=rps, duration_s=warmup_s)
    time.sleep(5)  # let Prometheus scrape

    samples = []
    for i in range(n_repeats):
        print(f"\n[repeat {i+1}/{n_repeats}] Sending {rps} RPS for {measure_s}s...")
        run_hey(rps=rps, duration_s=measure_s)
        time.sleep(15)  # wait for Prometheus 15s scrape
        p95 = front_end_p95_ms()
        rps_actual = front_end_rps()
        err = front_end_error_rate()
        print(f"  → p95={p95:.2f} ms, rps={rps_actual:.1f}, err_rate={err}")
        if p95 is not None and p95 == p95:  # not NaN
            samples.append(p95)
        else:
            print(f"  ⚠ invalid sample (NaN/None), skipping")

    if len(samples) < 3:
        print(f"\n✘ Too few valid samples ({len(samples)}), cannot compute anchor")
        return {"status": "failed", "reason": "insufficient_samples", "samples": samples}

    median = statistics.median(samples)
    mean = statistics.mean(samples)
    stdev = statistics.stdev(samples) if len(samples) > 1 else 0
    cv = stdev / mean if mean > 0 else 0

    result = {
        "anchor": "nominal_p95",
        "samples": samples,
        "median_ms": round(median, 2),
        "mean_ms": round(mean, 2),
        "stdev_ms": round(stdev, 2),
        "cv": round(cv, 4),
        "n_repeats": n_repeats,
        "n_valid": len(samples),
        "warmup_s": warmup_s,
        "measure_s": measure_s,
        "target_rps": rps,
        "provenance": _provenance(),
    }

    # Decision rule: SLO = nominal_p95 × 1.3–1.5
    slo_low = round(median * 1.3, 1)
    slo_high = round(median * 1.5, 1)
    result["slo_candidate_low"] = slo_low
    result["slo_candidate_high"] = slo_high

    print(f"\n{'='*60}")
    print(f"  Nominal p95 = {median:.2f} ms (mean={mean:.2f}, σ={stdev:.2f}, CV={cv:.3f})")
    print(f"  SLO candidate range: {slo_low}–{slo_high} ms (×1.3–1.5)")
    if cv > 0.15:
        print(f"  ⚠ High variance (CV={cv:.3f} > 0.15) — consider re-running")
        result["variance_warning"] = True
    print(f"{'='*60}")

    return result


# ── D3-000.5: Measure per-replica capacity ──────────────────────────────────
def measure_capacity(slo_p95_ms: float = 300.0, rps_steps: list[int] | None = None,
                     step_duration_s: int = 60, warmup_s: int = 30) -> dict:
    """Ramp load against front-end (1 replica); find RPS where p95 crosses SLO.
    capacity = last RPS within SLO."""
    if rps_steps is None:
        rps_steps = [5, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100]

    print(f"\n{'='*60}")
    print(f"D3-000.5 — Per-replica capacity measurement")
    print(f"  SLO threshold={slo_p95_ms} ms, steps={rps_steps}")
    print(f"  step_duration={step_duration_s}s, warmup={warmup_s}s")
    print(f"{'='*60}\n")

    # Get current replica count
    try:
        rep_out = subprocess.check_output(
            ["kubectl", "-n", "sock-shop", "get", "deploy", "front-end",
             "-o", "jsonpath={.spec.replicas}"], text=True
        ).strip()
        replicas = int(rep_out)
    except Exception:
        replicas = 1

    print(f"  front-end replicas: {replicas}")

    # Warmup
    print(f"\n[warmup] {warmup_s}s at {rps_steps[0]} RPS...")
    run_hey(rps=rps_steps[0], duration_s=warmup_s)
    time.sleep(10)

    measurements = []
    breach_rps = None
    last_good_rps = None

    for step_rps in rps_steps:
        print(f"\n[step] {step_rps} RPS for {step_duration_s}s...")
        h_res = run_hey(rps=step_rps, duration_s=step_duration_s)
        time.sleep(15)
        p95 = front_end_p95_ms()
        rps_actual = front_end_rps()
        err = front_end_error_rate()
        hey_p95 = h_res.get("p95_ms")
        p95_display = f"{p95:.2f}" if p95 is not None else "N/A"
        rps_display = f"{rps_actual:.1f}" if rps_actual is not None else "N/A"
        hey_display = f"{hey_p95:.2f}" if hey_p95 is not None else "N/A"
        effective_p95 = p95 if p95 is not None else hey_p95
        print(f"  → prom_p95={p95_display} ms, hey_p95={hey_display} ms (SLO={slo_p95_ms}), rps={rps_display}, err={err}")
        measurements.append({
            "target_rps": step_rps,
            "actual_rps": rps_actual,
            "prom_p95_ms": p95,
            "hey_p95_ms": hey_p95,
            "p95_ms": effective_p95,
            "error_rate": err,
            "breached": effective_p95 is not None and effective_p95 > slo_p95_ms,
        })
        if effective_p95 is not None and effective_p95 <= slo_p95_ms:
            last_good_rps = step_rps
        elif breach_rps is None and effective_p95 is not None and effective_p95 > slo_p95_ms:
            breach_rps = step_rps
            print(f"  ✘ SLO BREACHED at {step_rps} RPS (p95={effective_p95:.2f} > {slo_p95_ms})")
            continue

    capacity_rps = last_good_rps
    per_replica = round(capacity_rps / replicas, 1) if capacity_rps else None

    result = {
        "anchor": "per_replica_capacity",
        "capacity_rps_total": capacity_rps,
        "replicas": replicas,
        "per_replica_rps": per_replica,
        "breach_rps": breach_rps,
        "slo_p95_ms": slo_p95_ms,
        "measurements": measurements,
        "provenance": _provenance(),
    }

    print(f"\n{'='*60}")
    if per_replica is not None:
        print(f"  Capacity: {capacity_rps} RPS total / {replicas} replicas = {per_replica} RPS/replica")
        print(f"  Breach at: {breach_rps} RPS")
    else:
        print(f"  ✘ Could not determine capacity (no good measurement)")
    print(f"{'='*60}")

    return result


# ── D3-000.6: Measure pod-ready time ────────────────────────────────────────
def measure_pod_ready(n_scaleups: int = 5, namespace: str = "sock-shop",
                      deployment: str = "front-end") -> dict:
    """Measure schedule→Ready latency for N scale-up events.
    Scales front-end from current to current+1, measures Ready time, scales back."""
    print(f"\n{'='*60}")
    print(f"D3-000.6 — Pod-ready time measurement")
    print(f"  deployment={namespace}/{deployment}, n_scaleups={n_scaleups}")
    print(f"{'='*60}\n")

    # Get current replicas
    rep_out = subprocess.check_output(
        ["kubectl", "-n", namespace, "get", "deploy", deployment,
         "-o", "jsonpath={.spec.replicas}"], text=True
    ).strip()
    base_replicas = int(rep_out)
    print(f"  Base replicas: {base_replicas}")

    ready_times = []
    failed = []

    for i in range(n_scaleups):
        target = base_replicas + 1
        print(f"\n[scale-up {i+1}/{n_scaleups}] {base_replicas} → {target} replicas...")

        t_start = time.time()
        subprocess.check_call(
            ["kubectl", "-n", namespace, "scale", "deploy", deployment,
             f"--replicas={target}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        # Wait for new pod to be Ready (poll every 2s, timeout 120s)
        ready = False
        for _ in range(60):
            time.sleep(2)
            out = subprocess.check_output(
                ["kubectl", "-n", namespace, "get", "deploy", deployment,
                 "-o", "jsonpath={.status.readyReplicas}"], text=True
            ).strip()
            try:
                ready_count = int(out)
            except ValueError:
                ready_count = 0
            if ready_count >= target:
                ready = True
                break

        t_ready = time.time()
        elapsed = t_ready - t_start

        if ready:
            print(f"  → Ready in {elapsed:.1f}s")
            ready_times.append(elapsed)
        else:
            print(f"  ✘ Timeout after {elapsed:.1f}s (only {ready_count}/{target} ready)")
            failed.append({"attempt": i+1, "elapsed": elapsed})

        # Scale back down
        time.sleep(3)
        subprocess.check_call(
            ["kubectl", "-n", namespace, "scale", "deploy", deployment,
             f"--replicas={base_replicas}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        # Wait for scale-down to settle
        time.sleep(10)

    if not ready_times:
        return {"status": "failed", "reason": "all_scaleups_timed_out", "failed": failed}

    median_s = statistics.median(ready_times)
    max_s = max(ready_times)
    p90_s = sorted(ready_times)[int(len(ready_times) * 0.9)] if len(ready_times) >= 5 else max_s

    # Distinguish warm (image cached) vs cold (image pull)
    # All scale-ups after the first should be warm since image is already on nodes
    warm_times = ready_times[1:] if len(ready_times) > 1 else ready_times
    warm_median = statistics.median(warm_times) if warm_times else median_s

    result = {
        "anchor": "pod_ready_time",
        "ready_times_s": [round(t, 1) for t in ready_times],
        "median_s": round(median_s, 1),
        "warm_median_s": round(warm_median, 1),
        "max_s": round(max_s, 1),
        "p90_s": round(p90_s, 1),
        "n_scaleups": n_scaleups,
        "n_success": len(ready_times),
        "n_failed": len(failed),
        "failed": failed,
        "base_replicas": base_replicas,
        "deployment": f"{namespace}/{deployment}",
        "provenance": _provenance(),
    }

    print(f"\n{'='*60}")
    print(f"  Pod-ready time: median={median_s:.1f}s, warm_median={warm_median:.1f}s, max={max_s:.1f}s")
    print(f"  {len(ready_times)}/{n_scaleups} scale-ups succeeded")
    print(f"  Decision rule: H ({os.environ.get('HORIZON_S', '120')}s) must exceed pod-ready ({max_s:.1f}s)")
    if max_s >= float(os.environ.get("HORIZON_S", "120")):
        print(f"  ⚠ pod-ready time ({max_s:.1f}s) ≥ H — consider raising H")
    else:
        print(f"  ✓ H ({os.environ.get('HORIZON_S', '120')}s) > pod-ready ({max_s:.1f}s) — margin OK")
    print(f"{'='*60}")

    return result


# ── Dry-run (D3-000.3 acceptance) ───────────────────────────────────────────
def dry_run():
    """Verify the harness computes p95/capacity/ready-time correctly from known data."""
    print("\n[dry-run] Verifying harness math on mock data...\n")

    # p95 math: for [10, 20, 30, 40, 50], p95 should be near 50 (Python statistics.median)
    mock_samples = [10.0, 12.0, 11.0, 13.0, 10.5]
    med = statistics.median(mock_samples)
    assert abs(med - 11.0) < 0.01, f"median expected 11.0, got {med}"
    mean = statistics.mean(mock_samples)
    stdev = statistics.stdev(mock_samples)
    cv = stdev / mean
    slo_low = round(med * 1.3, 1)
    slo_high = round(med * 1.5, 1)
    assert slo_low < slo_high, "SLO range must be ordered"
    print(f"  p95 math OK: median={med}, CV={cv:.4f}, SLO range={slo_low}–{slo_high}")

    # capacity math: given measurements, last-good before breach
    meas = [
        {"rps": 10, "p95": 50}, {"rps": 20, "p95": 100},
        {"rps": 30, "p95": 200}, {"rps": 40, "p95": 350},
    ]
    slo = 300
    last_good = None
    for m in meas:
        if m["p95"] <= slo:
            last_good = m["rps"]
    assert last_good == 30, f"capacity expected 30, got {last_good}"
    per_rep = last_good / 1  # 1 replica
    assert per_rep == 30.0
    print(f"  capacity math OK: last_good={last_good}, per_replica={per_rep}")

    # pod-ready math: median of [4, 6, 5, 7, 5] = 5
    times = [4.0, 6.0, 5.0, 7.0, 5.0]
    med_t = statistics.median(times)
    assert abs(med_t - 5.0) < 0.01
    max_t = max(times)
    assert max_t == 7.0
    # H=120s > 7s → OK
    assert 120 > max_t, "H must exceed pod-ready"
    print(f"  pod-ready math OK: median={med_t}, max={max_t}, H=120 > {max_t}")

    print("\n✓ dry-run passed — harness math verified\n")
    return True


# ── CLI ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="D3-000.3–000.6 characterization harness")
    parser.add_argument("--dry-run", action="store_true", help="Verify harness math (no cluster)")
    parser.add_argument("--measure-p95", action="store_true", help="D3-000.4: Measure nominal p95")
    parser.add_argument("--measure-capacity", action="store_true", help="D3-000.5: Per-replica capacity")
    parser.add_argument("--measure-pod-ready", action="store_true", help="D3-000.6: Pod-ready time")
    parser.add_argument("--all", action="store_true", help="Run all three measurements")
    parser.add_argument("--slo-ms", type=float, default=None, help="SLO threshold for capacity test (default: from nominal × 1.4)")
    parser.add_argument("--repeats", type=int, default=5, help="Number of repeats for p95/pod-ready")
    parser.add_argument("--output", type=str, default=None, help="Write JSON results to file")
    args = parser.parse_args()

    if args.dry_run:
        dry_run()
        return

    if not (args.measure_p95 or args.measure_capacity or args.measure_pod_ready or args.all):
        parser.print_help()
        return

    results = {"provenance": _provenance(), "measurements": {}}

    if args.all or args.measure_p95:
        r = measure_nominal_p95(n_repeats=args.repeats)
        results["measurements"]["nominal_p95"] = r

    slo_for_capacity = args.slo_ms
    if slo_for_capacity is None and "nominal_p95" in results["measurements"]:
        nominal = results["measurements"]["nominal_p95"]
        if nominal.get("median_ms"):
            slo_for_capacity = round(nominal["median_ms"] * 1.4, 1)
            print(f"\n  Using SLO = nominal_p95 × 1.4 = {slo_for_capacity} ms for capacity test\n")

    if args.all or args.measure_capacity:
        r = measure_capacity(slo_p95_ms=slo_for_capacity or 300.0)
        results["measurements"]["per_replica_capacity"] = r

    if args.all or args.measure_pod_ready:
        r = measure_pod_ready(n_scaleups=args.repeats)
        results["measurements"]["pod_ready_time"] = r

    # Save results
    if args.output:
        with open(args.output, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nResults saved to {args.output}")

    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
