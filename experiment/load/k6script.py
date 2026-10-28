"""D3-005.1 — deterministic k6 script rendering from a regime profile.

The profile (RPS per 15 s step) becomes a k6 ``constant-arrival-rate`` stage
list: consecutive equal-target steps coalesce so scripts stay compact while
the schedule the generator plays back is EXACTLY the preseeded profile. Seeds
and regime names land in k6 tags so every results row can be attributed.

Reproducibility: same profile ⇒ byte-identical script (targets rounded to a
FIXED 3 decimal places; no wall clock anywhere).

Blast radius (PS-8): the script hits exactly one URL injected via
``__ENV.TARGET_URL`` and nothing else; the Job manifest enforces the deadline.
"""
from __future__ import annotations

import hashlib
import json

from . import config
from .regimes import Profile, regime_or_raise


def _stages(profile: Profile) -> list[tuple[int, str]]:
    """Coalesce consecutive steps with (practically) identical targets."""
    step_s = int(config.STEP_S)
    stages: list[tuple[int, str]] = []
    run_len, run_target = 0, None
    for value in profile.rps:
        target = str(int(round(float(value))))
        if run_target is not None and abs(float(run_target) - float(target)) < 1e-4:
            run_len += step_s
        else:
            if run_target is not None and run_len:
                stages.append((run_len, run_target))
            run_len, run_target = step_s, target
    if run_target is not None and run_len:
        stages.append((run_len, run_target))
    return stages


def render_script(profile: Profile) -> str:
    """Byte-reproducible k6 script for ``profile``."""
    regime_or_raise(profile.name)
    stages = _stages(profile)
    if not stages:
        raise ValueError(f"{profile.name}: empty profile cannot render a script")
    total = sum(duration for duration, _target in stages)
    if total != config.DURATION_S:
        raise ValueError(
            f"{profile.name}: stages cover {total}s, expected exactly "
            f"{config.DURATION_S} (duration cap, PS-8)"
        )
    stage_lines = ",\n      ".join(
        f"{{ duration: '{duration}s', target: {target} }}"
        for duration, target in stages
    )
    return f"""// D3-005 load harness — regime: {profile.name} (§9 Decision 3 shape)
// seed: {profile.seed}  base_rps: ⚙️ {profile.base_rps} (pre-characterization placeholder)
// profile: {profile.steps} steps × {config.STEP_S}s; total {config.DURATION_S}s (capped, PS-8)
// GENERATED — re-render with `python -m experiment.load --render {profile.name}`.
import http from 'k6/http';

export const options = {{
  discardResponseBodies: true,
  timeUnit: '1s',
  stages: [
      {stage_lines}
  ],
  maxDuration: '{config.DURATION_CAP_S}s',
  tags: {{
    regime: '{profile.name}',
    seed: '{profile.seed}',
    harness: 'experiment-load-d3-005',
    target: 'front-end',           // Decision 1 primary SLO service
  }},
}};

export default function () {{
  // single read-only GET — no writes, target fixed to the SLO edge (PS-8)
  http.get(__ENV.TARGET_URL);
}}
"""


def render_configmap(profile: Profile) -> tuple[str, dict]:
    """ConfigMap name + object carrying the rendered script (idempotent:
    identical profile ⇒ identical name ⇒ same ConfigMap, no churn)."""
    regime_or_raise(profile.name)
    script = render_script(profile)
    digest = hashlib.sha256(
        json.dumps(profile.to_dict()["rps"], sort_keys=True).encode()
    ).hexdigest()[:12]
    name = f"k6-script-{profile.name}-{profile.seed}-{digest}"
    return name, {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": name,
            "namespace": config.MANIFEST_NAMESPACE,
            "labels": {
                "app.kubernetes.io/part-of": "aiops-platform",
                "aiops.platform/component": "load-harness",
                "aiops.platform/regime": profile.name,
                "aiops.platform/seed": str(profile.seed),
            },
        },
        "data": {"script.js": script},
    }


__all__ = ["render_script", "render_configmap"]
