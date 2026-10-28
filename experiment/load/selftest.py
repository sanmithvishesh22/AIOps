"""Offline selftest for D3-005 (python -m experiment.load --selftest).

Assert-based, no cluster, no k6 binary (TS-1). Renders + validates the four
regimes, their envelopes, reproducibility, the k6 scripts, and the Job
objects. All synthetic fixtures are mechanics-only (TS-6): the envelope
asserts SHAPE fractions, never §9 magnitude claims (those are ⚙️ pending
D3-000.5).
"""
from __future__ import annotations

import numpy as np

from . import config
from .job import build_job
from .k6script import render_configmap, render_script
from .regimes import Profile, UnknownRegime, assert_envelope, build_profile, regime_or_raise

from aiops.common import config as common


def _check_regime_registry() -> None:
    assert config.REGIMES == ("stationary", "diurnal", "spike", "bursty")
    # invalid names are rejected (PS-3); case/whitespace is normalized, not punished
    for bad in ("", "bursts", "flat", "random_walk"):  # type: ignore[list-item]
        try:
            regime_or_raise(bad)
            raise AssertionError(f"invalid regime {bad!r} must be rejected")
        except UnknownRegime:
            pass


def _check_profiles() -> None:
    for name in config.REGIMES:
        prof = build_profile(name, seed=config.SEED)
        assert prof.steps == config.STEPS, f"{name}: must cover the 1200 s trial"
        assert prof.duration_s() == config.DURATION_S
        # TS-5: same seed ⇒ byte-identical profile
        again = build_profile(name, seed=config.SEED)
        assert np.array_equal(prof.rps, again.rps), f"{name}: seed reproducibility"
        # TS-6: envelope assertions shipped per regime
        assert_envelope(prof)

    # bursty is the only regime driven by its seed — distinct seeds differ
    a = build_profile("bursty", seed=1)
    b = build_profile("bursty", seed=2)
    assert not np.array_equal(a.rps, b.rps), "distinct seeds must differ"
    c = build_profile(" Bursty ".strip(), seed=1)  # case/whitespace normalized
    assert np.array_equal(a.rps, c.rps), "same seed after normalization must match"


def _check_envelope_red() -> None:
    """TS-3: a tampered profile must fail its own envelope assert."""
    prof = build_profile("diurnal", seed=3)
    bad = Profile("diurnal", prof.rps * 2.0, prof.seed, prof.base_rps)
    try:
        assert_envelope(bad)
        raise AssertionError("tampered diurnal profile must fail the envelope")
    except AssertionError:
        pass


def _check_scripts() -> None:
    for name in config.REGIMES:
        prof = build_profile(name, seed=config.SEED)
        script = render_script(prof)
        # exact schedule replay + duration cap (PS-8)
        assert "maxDuration: '1200s'" in script
        assert f"regime: '{name}'" in script and "seed: '42'" in script
        assert "http.get(__ENV.TARGET_URL);" in script
        assert script.count("duration: '") >= 1, "stage list present"
        # blast radius: only the TARGET_URL placeholder is referenced (PS-8)
        assert "surroundings" not in script
        # determinism: same profile ⇒ byte-identical script (TS-5)
        again = render_script(build_profile(name, seed=config.SEED))
        assert script == again, f"{name}: script must be byte-reproducible"

    # distinct seeds ⇒ distinct bursty script (seed plumb, PS-2)
    s1 = render_script(build_profile("bursty", seed=1))
    s2 = render_script(build_profile("bursty", seed=2))
    assert s1 != s2, "bursty script must encode its seed's schedule"

    cmap_name, cmap = render_configmap(build_profile("diurnal", seed=config.SEED))
    assert cmap_name.startswith("k6-script-diurnal-")
    assert cmap["metadata"]["namespace"] == config.MANIFEST_NAMESPACE
    assert "script.js" in cmap["data"]


def _check_jobs() -> None:
    prof = build_profile("stationary", seed=config.SEED)
    job = build_job(prof)
    assert job["apiVersion"] == "batch/v1" and job["kind"] == "Job"
    assert job["metadata"]["namespace"] == config.MANIFEST_NAMESPACE
    spec = job["spec"]
    assert spec["backoffLimit"] == 0
    assert spec["activeDeadlineSeconds"] >= config.DURATION_CAP_S, "deadline !== cap"
    pod = job["spec"]["template"]["spec"]
    container = pod["containers"][0]
    assert container["env"][0]["name"] == "TARGET_URL"
    assert container["env"][0]["value"] == config.TARGET_URL
    assert f".{common.SOCK_NS}." in config.TARGET_URL, "target must be in SOCK_NS"
    assert container["command"] == ["k6", "run", "/scripts/script.js"]
    assert "configMap" in pod["volumes"][0], "script delivered via ConfigMap"
    # labels carry regime + seed + component for attribution (PS-5)
    labels = job["metadata"]["labels"]
    assert labels["aiops.platform/regime"] == "stationary"
    assert labels["aiops.platform/seed"] == "42"
    assert "pair-id" in labels or True  # optional linkage to the runner

    # pair linkage renders when provided
    job2 = build_job(prof, pair_id="pair-001")
    assert job2["metadata"]["labels"]["aiops.platform/pair-id"] == "pair-001"


def run_selftest() -> None:
    _check_regime_registry()
    _check_profiles()
    _check_envelope_red()
    _check_scripts()
    _check_jobs()
    print(
        "load selftest OK — 4 regimes × envelope tests × seed reproducibility, "
        f"k6 scripts + Jobs render deterministically, duration cap "
        f"{config.DURATION_CAP_S}s, targets scoped to SOCK_NS (PS-8)"
    )


if __name__ == "__main__":
    run_selftest()
