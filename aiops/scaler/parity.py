"""D3-004.3 — resource-bound parity between the tuned HPA and the scaler.

The fairness guard: every ``deploy/platform/base/hpa-*.yaml`` must use the
SAME min/max replica bounds as the scaler (§9 Decision 4: 2/10). The CPU
target is deliberately **recorded, not asserted** — it stays a ⚙️ placeholder
until the characterization run replaces it via the predeclared procedure in
``deploy/platform/HPA_TUNING.md`` (tracking note D3-000.7).

Offline (parse + assert) and loud: a malformed/missing manifest or a bounds
mismatch fails with a message naming the file. Run directly:

    python3 -m aiops.scaler.parity
"""
from __future__ import annotations

from pathlib import Path

from . import config

REQUIRED_BEHAVIOR_KEYS = ("scaleUp", "scaleDown")
EXPECTED_API = "autoscaling/v2"


def manifests_dir() -> Path:
    """``deploy/platform/base`` relative to this repo checkout (no env needed)."""
    # aiops/scaler/parity.py -> parents: [scaler dir, aiops dir, repo root]
    return Path(__file__).resolve().parents[2] / "deploy" / "platform" / "base"


def check_hpa_parity(base_dir: Path | None = None) -> list[dict]:
    """Assert every hpa-*.yaml is schema-sane and bounds-identical to the scaler.

    Returns per-manifest info dicts (bounds, recorded ⚙️ CPU placeholder, apiversion).
    Raises AssertionError with a named-file message on the first violation.
    """
    import yaml

    directory = Path(base_dir) if base_dir is not None else manifests_dir()
    if not directory.is_dir():
        raise AssertionError(
            f"HPA parity cannot run: manifests directory missing: {directory}"
        )
    files = sorted(directory.glob("hpa-*.yaml"))
    if not files:
        raise AssertionError(
            f"no hpa-*.yaml manifests in {directory} — the tuned-HPA baseline "
            "(D3-004.1) is part of the lane contract; refusing to certify"
        )

    infos: list[dict] = []
    for path in files:
        doc = yaml.safe_load(path.read_text())
        if doc.get("apiVersion") != EXPECTED_API or doc.get("kind") != "HorizontalPodAutoscaler":
            raise AssertionError(
                f"{path.name}: expected {EXPECTED_API} HorizontalPodAutoscaler, "
                f"got {doc.get('apiVersion')}/{doc.get('kind')}"
            )
        spec = doc.get("spec") or {}
        lo, hi = spec.get("minReplicas"), spec.get("maxReplicas")
        if (lo, hi) != (config.MIN_REPLICAS, config.MAX_REPLICAS):
            raise AssertionError(
                f"{path.name}: bounds ({lo}, {hi}) != scaler bounds "
                f"({config.MIN_REPLICAS}, {config.MAX_REPLICAS}) — fairness "
                "guard failed (D3-004.3)"
            )
        ref = (spec.get("scaleTargetRef") or {})
        if not ref.get("apiVersion") or not ref.get("kind") or not ref.get("name"):
            raise AssertionError(f"{path.name}: scaleTargetRef incomplete")
        ns = (doc.get("metadata") or {}).get("namespace")
        if ns is None:
            raise AssertionError(
                f"{path.name}: metadata.namespace must be explicit ({config.SOCK_NS})"
            )
        metrics = spec.get("metrics") or []
        if not metrics:
            raise AssertionError(f"{path.name}: no metrics — comparator signal missing")
        m0 = metrics[0]
        if m0.get("type") != "Resource" or (m0.get("resource") or {}).get("name") != "cpu":
            raise AssertionError(
                f"{path.name}: first metric must be a cpu Resource metric "
                "(the reactive signal), got " + repr(m0)
            )
        behavior = spec.get("behavior") or {}
        for key in REQUIRED_BEHAVIOR_KEYS:
            if key not in behavior:
                raise AssertionError(
                    f"{path.name}: behavior.{key} must be set explicitly "
                    "(no silent cluster defaults, D3-004.1)"
                )
        cpu_target = (m0.get("resource") or {}).get("target") or {}
        placeholder = None
        if cpu_target.get("type") == "Utilization":
            placeholder = cpu_target.get("averageUtilization")
        infos.append({
            "file": path.name,
            "bounds": (lo, hi),
            "namespace": ns,
            "cpu_target_placeholder": placeholder,  # ⚙️ RECORDED, not asserted
            "api_version": doc.get("apiVersion"),
        })
    return infos


def main() -> int:
    infos = check_hpa_parity()
    for info in infos:
        cpu = info["cpu_target_placeholder"]
        print(
            f"hpa parity OK: {info['file']} bounds={info['bounds']} ns={info['namespace']} "
            f"cpu_target=⚙️{cpu} (placeholder — recorded, not asserted until D3-000.7)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["check_hpa_parity", "manifests_dir"]
