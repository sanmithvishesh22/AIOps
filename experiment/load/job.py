"""D3-005.1 — k6 Job object rendering (batch/v1).

The runner (D3-007) applies these objects programmatically; offline renders
are validated by the module selftest. Blast radius (PS-8):
  * the Job lives in the PLATFORM namespace (`aiops`), never sock-shop;
  * it only issues HTTP GETs to the SLO edge through TARGET_URL env;
  * `activeDeadlineSeconds` bounds it to the trial + margin — no runaway job;
  * resources are small and requests metric bounded.
"""
from __future__ import annotations

from . import config
from .k6script import render_configmap
from .regimes import Profile, regime_or_raise

DEADLINE_MARGIN_S = 300


def build_job(profile: Profile, *, pair_id: str | None = None, policy: str | None = None) -> dict:
    """Job manifest for one load trial of ``profile`` (pair_id optional)."""
    regime_or_raise(profile.name)
    cmap_name, _ = render_configmap(profile)
    labels = {
        "app.kubernetes.io/name": "k6-loadgen",
        "app.kubernetes.io/part-of": "aiops-platform",
        "aiops.platform/component": "load-harness",
        "aiops.platform/regime": profile.name,
        "aiops.platform/seed": str(profile.seed),
    }
    if pair_id:
        labels["aiops.platform/pair-id"] = str(pair_id)
    if policy:
        labels["aiops.platform/policy"] = str(policy)

    job_suffix = f"-{policy.replace('_', '-')}" if policy else ""
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": f"loadgen-{profile.name}-{profile.seed}{job_suffix}",
            "namespace": config.MANIFEST_NAMESPACE,
            "labels": labels,
        },
        "spec": {
            "backoffLimit": 0,                  # one clean attempt per run
            "activeDeadlineSeconds": config.DURATION_CAP_S + DEADLINE_MARGIN_S,
            "ttlSecondsAfterFinished": 3600,
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "restartPolicy": "Never",
                    "containers": [
                        {
                            "name": "k6",
                            "image": config.K6_IMAGE,
                            "imagePullPolicy": "IfNotPresent",
                            "command": ["k6", "run", "/scripts/script.js"],
                            "env": [
                                {
                                    "name": "TARGET_URL",
                                    "value": config.TARGET_URL,
                                }
                            ],
                            "resources": {
                                "requests": {"cpu": "250m", "memory": "256Mi"},
                                "limits": {"cpu": "1", "memory": "512Mi"},
                            },
                            "volumeMounts": [
                                {"name": "scripts", "mountPath": "/scripts/"}
                            ],
                        }
                    ],
                    "volumes": [
                        {"name": "scripts", "configMap": {"name": cmap_name}}
                    ],
                },
            },
        },
    }


__all__ = ["build_job"]
