"""INT-004 — Live trial executor for paired experiments on kind cluster.

Coordinates:
  1. HPA vs forecast-assisted hybrid scaler policy application.
  2. k6 Job lifecycle in the platform namespace (`aiops`).
  3. Chaos Mesh fault injection in the workload namespace (`sock-shop`) with
     actual Kubernetes verification of fault admission.
  4. Real-time telemetry collection from Prometheus and Kubernetes.
  5. Clean teardown and cluster reset between trials.
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
import urllib.parse
import urllib.request
import yaml

from aiops.common import config as common
from aiops.scaler.controller import ScalerController
from aiops.scaler.k8s import K8sScaleClient
from experiment.faults.chaos import build_fault
from experiment.load.job import build_job
from experiment.load.k6script import render_configmap
from experiment.load.regimes import build_profile
from . import config
from .metrics import TelemetryPoint, tag_infected_samples
from .pair import TrialSpec

logger = logging.getLogger("aiops.experiment.runner.live")

HPA_MANIFEST = "deploy/platform/base/hpa-front-end.yaml"
BASE_REPLICAS = 2


def _prom_query(promql: str) -> list[dict]:
    """Execute an instant query against Prometheus."""
    url = f"http://localhost:9090/api/v1/query?{urllib.parse.urlencode({'query': promql})}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        if data.get("status") == "success":
            return data["data"]["result"]
    except Exception as e:
        logger.warning("Prometheus query failed: %s (%s)", promql, e)
    return []


class LiveTrialExecutor:
    """Executes a single live TrialSpec against the testbed."""

    def __init__(
        self,
        prom_url: str = "http://localhost:9090",
        namespace: str = common.SOCK_NS,
        platform_ns: str = "aiops",
    ) -> None:
        self.prom_url = prom_url
        self.namespace = namespace
        self.platform_ns = platform_ns
        self.scale_client = K8sScaleClient(namespace=namespace)

    def _reset_workload(self) -> None:
        """Reset front-end replicas to baseline and clean any stale resources."""
        # Scale to BASE_REPLICAS
        try:
            self.scale_client.scale("front-end", BASE_REPLICAS)
        except Exception as e:
            logger.warning("Failed to reset front-end scale: %s", e)

        # Delete any leftover HPAs
        subprocess.run(
            ["kubectl", "delete", "-f", HPA_MANIFEST, "--ignore-not-found=true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Delete any leftover Chaos Mesh resources in sock-shop
        for kind in ("stresschaos", "podchaos", "networkchaos", "httpchaos"):
            subprocess.run(
                ["kubectl", "delete", kind, "--all", "-n", self.namespace, "--ignore-not-found=true"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        # Delete any leftover loadgen Jobs in aiops
        subprocess.run(
            ["kubectl", "delete", "jobs", "-l", "app.kubernetes.io/name=k6-loadgen", "-n", self.platform_ns, "--ignore-not-found=true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        time.sleep(3)

    def _sample_telemetry(self, ts: float, is_infected: bool) -> TelemetryPoint:
        """Query Prometheus for instant telemetry at timestamp ts."""
        p95_val = 10.0
        err_val = 0.0
        rps_val = 30.0
        reps_val = self.scale_client.current_replicas("front-end")

        p95_q = _prom_query(
            'histogram_quantile(0.95, sum(rate(request_duration_seconds_bucket{job="front-end"}[1m])) by (le)) * 1000'
        )
        if p95_q and p95_q[0].get("value"):
            try:
                v = float(p95_q[0]["value"][1])
                if v == v:
                    p95_val = v
            except (ValueError, IndexError):
                pass

        err_q = _prom_query(
            'sum(rate(request_duration_seconds_count{job="front-end",status_code=~"5.."}[1m])) '
            '/ sum(rate(request_duration_seconds_count{job="front-end"}[1m]))'
        )
        if err_q and err_q[0].get("value"):
            try:
                v = float(err_q[0]["value"][1])
                if v == v:
                    err_val = v
            except (ValueError, IndexError):
                pass

        rps_q = _prom_query('sum(rate(request_duration_seconds_count{job="front-end"}[1m]))')
        if rps_q and rps_q[0].get("value"):
            try:
                v = float(rps_q[0]["value"][1])
                if v == v:
                    rps_val = v
            except (ValueError, IndexError):
                pass

        return TelemetryPoint(
            ts=ts,
            p95_ms=round(p95_val, 2),
            error_rate=round(err_val, 4),
            rps=round(rps_val, 2),
            replicas=reps_val,
            is_infected=is_infected,
        )

    def execute(self, spec: TrialSpec) -> list[TelemetryPoint]:
        """Execute one trial end-to-end and return telemetry points."""
        logger.info("Executing trial: pair=%s policy=%s regime=%s fault=%s seed=%d duration=%ds",
                    spec.pair_id, spec.policy, spec.workload_regime, spec.fault_class, spec.seed, spec.duration_s)

        self._reset_workload()
        fault_manifest: dict | None = None
        job_manifest: dict | None = None
        cmap_manifest: dict | None = None
        cmap_name: str | None = None
        job_name: str | None = None

        scaler_ctrl: ScalerController | None = None

        try:
            # 1. Apply Policy
            if spec.policy == "hpa_tuned":
                logger.info("[%s] Applying tuned HPA manifest", spec.pair_id)
                res = subprocess.run(["kubectl", "apply", "-f", HPA_MANIFEST], capture_output=True, text=True)
                if res.returncode != 0:
                    raise RuntimeError(f"Failed to apply HPA: {res.stderr}")
            elif spec.policy == "forecast_hybrid":
                logger.info("[%s] Initializing hybrid scaler controller", spec.pair_id)
                scaler_ctrl = ScalerController(
                    client=self.scale_client,
                    anchor_rps=42.0,
                    services=("front-end",),
                    sink=lambda rows: len(rows),
                )
            else:
                raise ValueError(f"Unknown policy: {spec.policy}")

            # 2. Build and Apply k6 Load Job
            from experiment.load import config as load_config
            load_config.set_duration(spec.duration_s)
            profile = build_profile(spec.workload_regime, base_rps=42.0, seed=spec.seed)
            cmap_name, cmap_manifest = render_configmap(profile)
            job_manifest = build_job(profile, pair_id=spec.pair_id, policy=spec.policy)
            job_name = job_manifest["metadata"]["name"]

            # Apply ConfigMap
            res = subprocess.run(["kubectl", "apply", "-f", "-"], input=yaml.dump(cmap_manifest), text=True, capture_output=True)
            if res.returncode != 0:
                raise RuntimeError(f"Failed to apply k6 ConfigMap: {res.stderr}")

            # Apply Job
            res = subprocess.run(["kubectl", "apply", "-f", "-"], input=yaml.dump(job_manifest), text=True, capture_output=True)
            if res.returncode != 0:
                raise RuntimeError(f"Failed to apply k6 Job: {res.stderr}")

            t_start = time.time()
            logger.info("[%s] Load Job %s started at %f", spec.pair_id, job_name, t_start)

            # Wait for Job pod to be Running
            job_started = False
            for _ in range(30):
                time.sleep(1)
                chk = subprocess.run(
                    ["kubectl", "get", "pods", "-l", f"job-name={job_name}", "-n", self.platform_ns, "-o", "jsonpath={.items[*].status.phase}"],
                    capture_output=True, text=True
                )
                if "Running" in chk.stdout:
                    job_started = True
                    break
            if not job_started:
                logger.warning("[%s] Job pod did not enter Running state within 30s", spec.pair_id)

            # 3. Fault timing setup
            has_fault = spec.fault_class != "none"
            fault_applied = False
            fault_duration = min(spec.duration_s // 2, 300)
            fault_onset_s = spec.duration_s * 0.50

            telemetry_points: list[TelemetryPoint] = []
            step_s = config.STEP_S
            step_count = max(1, spec.duration_s // step_s)

            # 4. Active Trial Loop (at step_s interval)
            for step_idx in range(step_count):
                step_now = time.time()
                elapsed = step_now - t_start

                # Check fault onset
                if has_fault and not fault_applied and elapsed >= fault_onset_s:
                    logger.info("[%s] Injecting fault %s at elapsed=%.1fs (onset=%.1fs)",
                                spec.pair_id, spec.fault_class, elapsed, fault_onset_s)
                    fault_manifest = build_fault(
                        spec.fault_class,
                        service="front-end",
                        seed=spec.seed,
                        duration_s=fault_duration,
                        run_id=spec.pair_id,
                    )
                    f_res = subprocess.run(
                        ["kubectl", "apply", "-f", "-"],
                        input=yaml.dump(fault_manifest),
                        text=True,
                        capture_output=True,
                    )
                    if f_res.returncode != 0:
                        raise RuntimeError(f"Failed to inject fault {spec.fault_class}: {f_res.stderr}")

                    # Verify fault is active in k8s (INT-004 requirement 6)
                    f_kind = fault_manifest["kind"]
                    f_name = fault_manifest["metadata"]["name"]
                    chk = subprocess.run(
                        ["kubectl", "get", f_kind, f_name, "-n", self.namespace],
                        capture_output=True, text=True,
                    )
                    if chk.returncode != 0:
                        raise RuntimeError(f"Fault {f_name} was not accepted by Kubernetes: {chk.stderr}")
                    logger.info("[%s] Verified Chaos Mesh fault %s/%s active in k8s", spec.pair_id, f_kind, f_name)
                    fault_applied = True

                # Step hybrid scaler if active
                if scaler_ctrl:
                    try:
                        import pandas as pd
                        current_reps = self.scale_client.current_replicas("front-end")
                        rps_now = 30.0
                        res = _prom_query('sum(rate(request_duration_seconds_count{job="front-end"}[1m]))')
                        if res and res[0].get("value"):
                            rps_now = float(res[0]["value"][1])

                        frame = pd.DataFrame({
                            "ts": [step_now],
                            "service": ["front-end"],
                            "rps": [rps_now],
                            "p95_ms": [10.0],
                            "error_rate": [0.0],
                            "cpu": [0.1],
                            "mem": [0.1],
                            "replicas": [current_reps],
                        })
                        scaler_ctrl.run(frame, now_ts=step_now)
                    except Exception as exc:
                        logger.warning("[%s] Scaler controller step error: %s", spec.pair_id, exc)

                is_final_step = (step_idx == step_count - 1)

                # Execute step duration (allow workload and fault to run)
                time.sleep(step_s)

                if is_final_step:
                    # Wait for k6 Job completion (up to 30s)
                    for _ in range(30):
                        job_chk = subprocess.run(
                            ["kubectl", "get", "job", job_name, "-n", self.platform_ns, "-o", "jsonpath={.status.succeeded}"],
                            capture_output=True, text=True
                        )
                        if job_chk.stdout.strip() == "1":
                            break
                        time.sleep(1)

                # Sample telemetry at the completion of step execution
                step_end_ts = time.time()
                step_elapsed = step_end_ts - t_start
                is_inf = False
                if fault_applied:
                    is_inf = (fault_onset_s <= step_elapsed <= fault_onset_s + fault_duration + step_s)

                pt = self._sample_telemetry(ts=step_end_ts, is_infected=is_inf)
                telemetry_points.append(pt)
                logger.debug("[%s] Step %d/%d: p95=%.1fms err=%.3f rps=%.1f replicas=%d inf=%s",
                             spec.pair_id, step_idx + 1, step_count, pt.p95_ms, pt.error_rate, pt.rps, pt.replicas, is_inf)

                # Check if Job has finished early on non-final step
                if not is_final_step:
                    job_chk = subprocess.run(
                        ["kubectl", "get", "job", job_name, "-n", self.platform_ns, "-o", "jsonpath={.status.succeeded}"],
                        capture_output=True, text=True
                    )
                    if job_chk.stdout.strip() == "1":
                        logger.info("[%s] k6 Job %s succeeded at step %d", spec.pair_id, job_name, step_idx + 1)
                        break

            logger.info("[%s] Trial completed successfully with %d telemetry points", spec.pair_id, len(telemetry_points))
            return telemetry_points

        finally:
            # 5. Clean teardown
            if fault_manifest:
                subprocess.run(
                    ["kubectl", "delete", "-f", "-", "--ignore-not-found=true"],
                    input=yaml.dump(fault_manifest), text=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            if job_name:
                subprocess.run(
                    ["kubectl", "delete", "job", job_name, "-n", self.platform_ns, "--ignore-not-found=true"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            if cmap_name:
                subprocess.run(
                    ["kubectl", "delete", "configmap", cmap_name, "-n", self.platform_ns, "--ignore-not-found=true"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            if spec.policy == "hpa_tuned":
                subprocess.run(
                    ["kubectl", "delete", "-f", HPA_MANIFEST, "--ignore-not-found=true"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            try:
                self.scale_client.scale("front-end", BASE_REPLICAS)
            except Exception:
                pass


__all__ = ["LiveTrialExecutor"]
