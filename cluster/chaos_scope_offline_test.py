#!/usr/bin/env python3
"""Offline SEC-001 guard: Chaos Mesh must stay confined to SOCK_NS.

This is a *strict static configuration regression guard*, not a Helm renderer
and not a live cluster test. It proves only that this repository keeps the
approved Chaos Mesh bootstrap invocation and the approved values-file structure.
It cannot prove how Helm merges values, what a live cluster runs, or that an
operator did not bypass the script.

Design: fail closed. The guard accepts only the explicitly approved command and
the exact approved values structure. Anything ambiguous or unsupported is
rejected rather than interpreted. It deliberately does not try to implement
general Helm or YAML semantics.

Checks:
  * bootstrap pins chaos-mesh/chaos-mesh 2.8.7 and uses the approved release;
  * bootstrap applies cluster/chaos-mesh-values.yaml exactly once;
  * bootstrap preserves the release namespace, containerd runtime/socket,
    --create-namespace, --wait and --timeout 10m;
  * bootstrap rejects extra values files, --set-json/--set-file/--set-literal/
    --set-string/--post-renderer/--reuse-values/--reset-values and unknown flags;
  * the values file is the exact approved structure: clusterScoped false,
    controllerManager.targetNamespace == project SOCK_NS,
    controllerManager.serviceAccountCreate true, rbac.create true, and
    dnsServer.create false (DNSChaos is not in the ratified taxonomy);
  * duplicate, quoted, flow-style, anchored, aliased and tagged YAML forms are
    rejected;
  * the values namespace agrees with aiops/common/config.py and the Makefile.

Negative cases mutate a canonical in-memory fixture and must be rejected for the
expected reason, so a regression in the guard itself is caught. No third-party
dependencies, no cluster, no network, no temporary files.
"""
from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

CHART = "chaos-mesh/chaos-mesh"
CHART_VERSION = "2.8.7"
RELEASE = "chaos-mesh"
RELEASE_NAMESPACE = "chaos-mesh"
VALUES_FILE = "cluster/chaos-mesh-values.yaml"
BOOTSTRAP_FILE = "cluster/bootstrap.sh"
CONFIG_FILE = "aiops/common/config.py"
MAKEFILE_FILE = "Makefile"
CONTRACT_FILE = "docs/CONTRACTS.md"
TIMEOUT = "10m"
REQUIRED_SETS = (
    "chaosDaemon.runtime=containerd",
    "chaosDaemon.socketPath=/run/containerd/containerd.sock",
)
CANONICAL_BOOTSTRAP = (
    "#!/usr/bin/env bash\n"
    "set -euo pipefail\n"
    'cd "$(dirname "$0")/.."\n'
    "helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \\\n"
    "  --namespace monitoring --create-namespace \\\n"
    "  --values deploy/monitoring/kps-values.yaml --wait --timeout 10m\n"
    "helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh \\\n"
    "  --version 2.8.7 \\\n"
    "  --namespace chaos-mesh --create-namespace \\\n"
    "  --values cluster/chaos-mesh-values.yaml \\\n"
    "  --set chaosDaemon.runtime=containerd \\\n"
    "  --set chaosDaemon.socketPath=/run/containerd/containerd.sock "
    "--wait --timeout 10m\n"
)
CANONICAL_VALUES = (
    "clusterScoped: false\n"
    "\n"
    "controllerManager:\n"
    "  targetNamespace: sock-shop\n"
    "  serviceAccountCreate: true\n"
    "\n"
    "rbac:\n"
    "  create: true\n"
    "\n"
    "dnsServer:\n"
    "  create: false\n"
)
CANONICAL_CONFIG = 'SOCK_NS = os.environ.get("SOCK_NS", "sock-shop")\n'
CANONICAL_MAKEFILE = "SOCK_NS := sock-shop\n"
CANONICAL_CONTRACT = "| `SOCK_NS` | `sock-shop` | namespace under test |\n"
FORBIDDEN_SET_KEYS = (
    "clusterScoped",
    "controllerManager.targetNamespace",
    "dnsServer.targetNamespace",
    "rbac.create",
    "controllerManager.serviceAccountCreate",
)
VALUE_FLAGS = {
    "--version": "version",
    "--namespace": "namespace",
    "--values": "values",
    "-f": "values",
    "--set": "set",
    "--timeout": "timeout",
}
BOOL_FLAGS = {"--install", "--create-namespace", "--wait"}
DANGEROUS_FLAGS = {
    "--set-json",
    "--set-file",
    "--set-literal",
    "--set-string",
    "--post-renderer",
    "--post-renderer-args",
    "--reuse-values",
    "--reset-values",
}
EXPECTED_NEGATIVE_CASES = 91
EXPECTED_NAMESPACE_CASES = 9
EXPECTED_POSITIVE_VARIANTS = 12

KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")
VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
NAMESPACE_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
SOCK_NS_RE = re.compile(
    r'^\s*SOCK_NS\s*=\s*os\.environ\.get\(\s*["\']SOCK_NS["\']\s*,'
    r'\s*["\']([^"\']+)["\']\s*\)\s*$',
    re.MULTILINE,
)
MAKE_SOCK_NS_RE = re.compile(r"^SOCK_NS\s*:?=\s*(\S+)\s*$", re.MULTILINE)
CONTRACT_SOCK_NS_RE = re.compile(
    r"^\|\s*`SOCK_NS`\s*\|\s*`([^`]+)`\s*\|", re.MULTILINE
)


def _replace_once(text: str, old: str, new: str) -> str:
    """Replace exactly one occurrence, failing if the mutation target drifted."""
    count = text.count(old)
    if count != 1:
        raise AssertionError(f"mutation target count {count} for {old!r}")
    return text.replace(old, new, 1)


def _strip_comment(line: str) -> str:
    if "\t" in line:
        raise ValueError("tabs are not allowed")
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return ""
    if "#" in line:
        raise ValueError("inline comments are not allowed")
    return line.rstrip()


def _scalar(value: str):
    if value == "true":
        return True
    if value == "false":
        return False
    return value


def parse_values(text: str) -> dict:
    """Parse the strict canonical YAML subset used by chaos-mesh-values.yaml.

    Only top-level scalars and one level of two-space-indented mappings are
    accepted. Quoted keys/values, flow mappings/sequences, anchors, aliases,
    tags, block scalars, tabs, inline comments, odd indentation, deeper nesting
    and duplicate keys are rejected so an ambiguous file fails closed.
    """
    data: dict = {}
    current = None
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line:
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent not in (0, 2):
            raise ValueError("indentation must be 0 or 2 spaces")
        key, sep, value = line.strip().partition(":")
        key = key.strip()
        value = value.strip()
        if not sep or not key:
            raise ValueError(f"unsupported line: {raw!r}")
        if not KEY_RE.fullmatch(key):
            raise ValueError(f"unsupported key syntax: {key!r}")
        if value:
            if not VALUE_RE.fullmatch(value):
                raise ValueError(f"unsupported value syntax: {value!r}")
        if indent == 0:
            if key in data:
                raise ValueError(f"duplicate key: {key}")
            if value == "":
                data[key] = {}
                current = key
            else:
                data[key] = _scalar(value)
                current = None
        else:
            if current is None or not isinstance(data.get(current), dict):
                raise ValueError(f"unexpected nested key: {key}")
            if key in data[current]:
                raise ValueError(f"duplicate key: {current}.{key}")
            if value == "":
                raise ValueError("nested mappings deeper than one level are not supported")
            data[current][key] = _scalar(value)
    return data


def _logical_lines(text: str) -> list[str]:
    text = text.replace("\\\r\n", " ").replace("\\\n", " ")
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _chaos_helm_lines(text: str) -> list[str]:
    return [line for line in _logical_lines(text) if CHART in line]


def _check_chaos_command(line: str) -> list[str]:
    errors: list[str] = []
    try:
        tokens = shlex.split(line, comments=True)
    except ValueError as exc:
        return [f"bootstrap: cannot parse helm command: {exc}"]

    if len(tokens) < 2 or tokens[0] != "helm" or tokens[1] != "upgrade":
        return ["bootstrap: Chaos Mesh command must be 'helm upgrade ...'"]

    seen: dict[str, int] = {}
    positionals: list[str] = []
    values_args: list[str] = []
    sets: list[str] = []
    version = None
    namespace = None
    timeout = None
    install = None
    create_namespace = None
    wait = None

    index = 2
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("-"):
            positionals.append(token)
            index += 1
            continue

        name, sep, inline = token.partition("=")
        if (
            token.startswith("-f")
            and not token.startswith("--")
            and token != "-f"
            and not sep
        ):
            name, sep, inline = "-f", "=", token[2:]
        if name in DANGEROUS_FLAGS:
            errors.append(f"bootstrap: {name} is not permitted for Chaos Mesh")
            index += 1
            continue
        if name not in VALUE_FLAGS and name not in BOOL_FLAGS:
            errors.append(f"bootstrap: unsupported Helm flag {name!r}")
            index += 1
            continue

        canonical = VALUE_FLAGS.get(name, name)
        if name != "--set" and canonical in seen:
            errors.append(f"bootstrap: duplicate {name}")
        seen[canonical] = seen.get(canonical, 0) + 1

        if name in VALUE_FLAGS:
            if sep:
                value = inline
            else:
                if index + 1 >= len(tokens) or tokens[index + 1].startswith("-"):
                    errors.append(f"bootstrap: {name} requires a value")
                    index += 1
                    continue
                value = tokens[index + 1]
                index += 1
            if name == "--version":
                version = value
            elif name == "--namespace":
                namespace = value
            elif canonical == "values":
                values_args.append(value)
            elif name == "--set":
                sets.append(value)
            elif name == "--timeout":
                timeout = value
        else:
            if sep:
                if inline not in ("true", "false"):
                    errors.append(f"bootstrap: {name} must be true or false")
                    index += 1
                    continue
                bool_value = inline == "true"
            else:
                bool_value = True
            if name == "--install":
                install = bool_value
            elif name == "--create-namespace":
                create_namespace = bool_value
            elif name == "--wait":
                wait = bool_value
        index += 1

    if positionals != [RELEASE, CHART]:
        errors.append(f"bootstrap: positional args must be {RELEASE} {CHART}")
    if install is not True:
        errors.append("bootstrap: --install must be enabled")
    if version != CHART_VERSION:
        errors.append(f"bootstrap: chart version must be pinned to {CHART_VERSION}")
    if namespace != RELEASE_NAMESPACE:
        errors.append(f"bootstrap: release namespace must remain {RELEASE_NAMESPACE}")
    if create_namespace is not True:
        errors.append("bootstrap: --create-namespace must be true")
    if wait is not True:
        errors.append("bootstrap: --wait must be preserved")
    if timeout != TIMEOUT:
        errors.append(f"bootstrap: --timeout must be {TIMEOUT}")
    if len(values_args) != 1:
        errors.append(f"bootstrap: exactly one --values {VALUES_FILE} is required")
    elif values_args[0] != VALUES_FILE:
        errors.append(f"bootstrap: --values must be {VALUES_FILE}")

    assignments: list[str] = []
    for raw in sets:
        if "\\" in raw:
            errors.append("bootstrap: escaped --set values are not supported")
            continue
        parts = [part.strip() for part in raw.split(",")]
        if any(not part for part in parts):
            errors.append("bootstrap: empty --set assignment")
            continue
        assignments.extend(parts)
    if len(assignments) != len(REQUIRED_SETS) or set(assignments) != set(REQUIRED_SETS):
        errors.append(
            "bootstrap: --set must contain exactly "
            + " and ".join(REQUIRED_SETS)
        )
    for assignment in assignments:
        for key in FORBIDDEN_SET_KEYS:
            if assignment.startswith(key + "="):
                errors.append(
                    f"bootstrap: {key} must come from {VALUES_FILE}, not --set"
                )
    return errors


def check_bootstrap(text: str) -> list[str]:
    errors: list[str] = []
    logical = _logical_lines(text)
    upgrade_lines = [line for line in logical if line.startswith("helm upgrade ")]
    if len(upgrade_lines) != 2:
        errors.append(
            "bootstrap: exactly two helm upgrade invocations are expected "
            "(monitoring and chaos-mesh)"
        )
    for line in logical:
        if "helm upgrade" in line and not line.startswith("helm upgrade "):
            errors.append(
                "bootstrap: helm upgrade must be a direct command, not wrapped"
            )

    lines = _chaos_helm_lines(text)
    approved_line = None
    if not lines:
        errors.append(f"bootstrap: no 'helm upgrade --install' for {CHART}")
    elif len(lines) > 1:
        errors.append("bootstrap: multiple Chaos Mesh helm invocations are not allowed")
    else:
        approved_line = lines[0]
        errors.extend(_check_chaos_command(approved_line))

    for line in upgrade_lines:
        if line == approved_line:
            continue
        try:
            tokens = shlex.split(line, comments=True)
        except ValueError:
            continue
        if RELEASE in tokens:
            errors.append(
                "bootstrap: another helm upgrade targets the chaos-mesh release"
            )
        for index, token in enumerate(tokens):
            if token == "--namespace" and index + 1 < len(tokens):
                if tokens[index + 1] == RELEASE_NAMESPACE:
                    errors.append(
                        "bootstrap: another helm upgrade targets the chaos-mesh namespace"
                    )
            elif token == f"--namespace={RELEASE_NAMESPACE}":
                errors.append(
                    "bootstrap: another helm upgrade targets the chaos-mesh namespace"
                )

    for line in logical:
        if line.startswith(("helm install ", "helm uninstall ", "helm delete ")):
            try:
                tokens = shlex.split(line, comments=True)
            except ValueError:
                continue
            if RELEASE in tokens:
                errors.append(
                    "bootstrap: only the approved helm upgrade may manage the "
                    "chaos-mesh release"
                )

    if 'cd "$(dirname "$0")/.."' not in [line.strip() for line in logical]:
        errors.append('bootstrap: must cd to the repository root before using the values path')
    return errors
def _check_keys(errors: list[str], label: str, mapping: dict, allowed: set[str]) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        errors.append(f"{label}: unexpected key(s): {', '.join(unknown)}")
    missing = sorted(allowed - set(mapping))
    if missing:
        errors.append(f"{label}: missing key(s): {', '.join(missing)}")


def check_values(text: str, sock_ns: str | None) -> list[str]:
    errors: list[str] = []
    try:
        data = parse_values(text)
    except ValueError as exc:
        return [f"values: {exc}"]

    _check_keys(
        errors,
        "values",
        data,
        {"clusterScoped", "controllerManager", "rbac", "dnsServer"},
    )
    if data.get("clusterScoped") is not False:
        errors.append("values: clusterScoped must be boolean false")
    if not sock_ns:
        errors.append("values: SOCK_NS is unavailable; cannot verify target namespace")

    controller = data.get("controllerManager")
    if not isinstance(controller, dict):
        errors.append("values: controllerManager must be a mapping")
    else:
        _check_keys(
            errors,
            "values: controllerManager",
            controller,
            {"targetNamespace", "serviceAccountCreate"},
        )
        if controller.get("targetNamespace") != sock_ns:
            errors.append(
                f"values: controllerManager.targetNamespace must equal SOCK_NS ({sock_ns})"
            )
        if controller.get("serviceAccountCreate") is not True:
            errors.append(
                "values: controllerManager.serviceAccountCreate must be boolean true"
            )

    rbac = data.get("rbac")
    if not isinstance(rbac, dict):
        errors.append("values: rbac must be a mapping")
    else:
        _check_keys(errors, "values: rbac", rbac, {"create"})
        if rbac.get("create") is not True:
            errors.append("values: rbac.create must be boolean true")

    dns = data.get("dnsServer")
    if not isinstance(dns, dict):
        errors.append("values: dnsServer must be a mapping")
    else:
        _check_keys(errors, "values: dnsServer", dns, {"create"})
        if dns.get("create") is not False:
            errors.append(
                "values: dnsServer.create must be boolean false (DNSChaos is unused)"
            )
    return errors


def check_namespace_sources(
    config_text: str, makefile_text: str, contract_text: str
) -> tuple[list[str], str | None]:
    errors: list[str] = []
    config_match = SOCK_NS_RE.search(config_text)
    make_match = MAKE_SOCK_NS_RE.search(makefile_text)
    contract_match = CONTRACT_SOCK_NS_RE.search(contract_text)
    sources = [
        (CONFIG_FILE, config_match.group(1) if config_match else None),
        (MAKEFILE_FILE, make_match.group(1) if make_match else None),
        (CONTRACT_FILE, contract_match.group(1) if contract_match else None),
    ]

    for label, namespace in sources:
        if namespace is None:
            errors.append(f"namespace: cannot find SOCK_NS default in {label}")
        elif not NAMESPACE_RE.fullmatch(namespace) or len(namespace) > 63:
            errors.append(
                f"namespace: {label} SOCK_NS {namespace!r} is not a valid namespace"
            )

    present = [(label, namespace) for label, namespace in sources if namespace]
    if len({namespace for _, namespace in present}) > 1:
        errors.append(
            "namespace: SOCK_NS sources disagree: "
            + ", ".join(f"{label}={namespace}" for label, namespace in present)
        )
    return errors, (sources[2][1] if isinstance(sources[2][1], str) else None)
def _mutate_chaos_command(text: str, old: str, new: str) -> str:
    """Replace one `old` inside the Chaos Mesh helm command only."""
    anchor = f"helm upgrade --install {RELEASE} {CHART}"
    start = text.find(anchor)
    if start == -1:
        raise AssertionError(f"mutation anchor not found: {anchor!r}")
    index = text.find(old, start)
    if index == -1:
        raise AssertionError(f"mutation target not found after anchor: {old!r}")
    if text.find(old, index + len(old)) != -1:
        raise AssertionError(f"mutation target is ambiguous after anchor: {old!r}")
    return text[:index] + new + text[index + len(old):]


def positive_variants(bootstrap_text: str) -> list[tuple[str, str]]:
    """Safe equivalent Helm syntax that the strict guard must still accept."""
    combined_sets = (
        "  --set chaosDaemon.runtime=containerd \\\n"
        "  --set chaosDaemon.socketPath=/run/containerd/containerd.sock "
    )
    return [
        (
            "bootstrap: --version=2.8.7",
            _mutate_chaos_command(
                bootstrap_text, "--version 2.8.7", "--version=2.8.7"
            ),
        ),
        (
            "bootstrap: --namespace=chaos-mesh",
            _mutate_chaos_command(
                bootstrap_text, "--namespace chaos-mesh", "--namespace=chaos-mesh"
            ),
        ),
        (
            "bootstrap: --values=...",
            _mutate_chaos_command(
                bootstrap_text,
                f"--values {VALUES_FILE}",
                f"--values={VALUES_FILE}",
            ),
        ),
        (
            "bootstrap: -f ...",
            _mutate_chaos_command(
                bootstrap_text,
                f"--values {VALUES_FILE}",
                f"-f {VALUES_FILE}",
            ),
        ),
        (
            "bootstrap: -f=...",
            _mutate_chaos_command(
                bootstrap_text,
                f"--values {VALUES_FILE}",
                f"-f={VALUES_FILE}",
            ),
        ),
        (
            "bootstrap: -f<path>",
            _mutate_chaos_command(
                bootstrap_text,
                f"--values {VALUES_FILE}",
                f"-f{VALUES_FILE}",
            ),
        ),
        (
            "bootstrap: combined --set",
            _replace_once(
                bootstrap_text,
                combined_sets,
                "  --set chaosDaemon.runtime=containerd,"
                "chaosDaemon.socketPath=/run/containerd/containerd.sock ",
            ),
        ),
        (
            "bootstrap: --set=...",
            _mutate_chaos_command(
                bootstrap_text,
                "--set chaosDaemon.runtime=containerd",
                "--set=chaosDaemon.runtime=containerd",
            ),
        ),
        (
            "bootstrap: --create-namespace=true",
            _mutate_chaos_command(
                bootstrap_text,
                "--create-namespace",
                "--create-namespace=true",
            ),
        ),
        (
            "bootstrap: --timeout=10m",
            _mutate_chaos_command(
                bootstrap_text, "--timeout 10m", "--timeout=10m"
            ),
        ),
        (
            "bootstrap: --wait=true",
            _mutate_chaos_command(bootstrap_text, "--wait", "--wait=true"),
        ),
        (
            "bootstrap: --install=true",
            _mutate_chaos_command(
                bootstrap_text, "--install", "--install=true"
            ),
        ),
    ]
def _values_negative_cases(
    bootstrap_text: str, values_text: str
) -> list[tuple[str, str, str, str]]:
    return [
        (
            "values: clusterScoped true",
            bootstrap_text,
            _replace_once(values_text, "clusterScoped: false", "clusterScoped: true"),
            "clusterScoped",
        ),
        (
            "values: clusterScoped quoted string",
            bootstrap_text,
            _replace_once(
                values_text, "clusterScoped: false", 'clusterScoped: "false"'
            ),
            "unsupported value",
        ),
        (
            "values: clusterScoped missing",
            bootstrap_text,
            _replace_once(values_text, "clusterScoped: false\n", ""),
            "clusterScoped",
        ),
        (
            "values: clusterScoped duplicate plain",
            bootstrap_text,
            values_text + "\nclusterScoped: true\n",
            "duplicate key",
        ),
        (
            "values: clusterScoped quoted duplicate key",
            bootstrap_text,
            values_text + '\n"clusterScoped": true\n',
            "unsupported key",
        ),
        (
            "values: clusterScoped flow sequence",
            bootstrap_text,
            _replace_once(
                values_text, "clusterScoped: false", "clusterScoped: [false]"
            ),
            "unsupported value",
        ),
        (
            "values: clusterScoped anchor",
            bootstrap_text,
            _replace_once(
                values_text, "clusterScoped: false", "clusterScoped: &scope false"
            ),
            "unsupported value",
        ),
        (
            "values: clusterScoped alias",
            bootstrap_text,
            _replace_once(
                values_text, "clusterScoped: false", "clusterScoped: *scope"
            ),
            "unsupported value",
        ),
        (
            "values: clusterScoped tag",
            bootstrap_text,
            _replace_once(
                values_text, "clusterScoped: false", "clusterScoped: !!bool false"
            ),
            "unsupported value",
        ),
        (
            "values: clusterScoped block scalar",
            bootstrap_text,
            _replace_once(values_text, "clusterScoped: false", "clusterScoped: |"),
            "unsupported value",
        ),
        (
            "values: clusterScoped null",
            bootstrap_text,
            _replace_once(values_text, "clusterScoped: false", "clusterScoped: null"),
            "clusterScoped",
        ),
        (
            "values: clusterScoped uppercase FALSE",
            bootstrap_text,
            _replace_once(values_text, "clusterScoped: false", "clusterScoped: FALSE"),
            "clusterScoped",
        ),
        (
            "values: inline comment",
            bootstrap_text,
            _replace_once(
                values_text, "clusterScoped: false", "clusterScoped: false # comment"
            ),
            "inline comment",
        ),
        (
            "values: controller target wrong namespace",
            bootstrap_text,
            _replace_once(
                values_text,
                "  targetNamespace: sock-shop",
                "  targetNamespace: chaos-mesh",
            ),
            "targetNamespace",
        ),
        (
            "values: controller target missing",
            bootstrap_text,
            _replace_once(values_text, "  targetNamespace: sock-shop\n", ""),
            "targetNamespace",
        ),
        (
            "values: controller target quoted",
            bootstrap_text,
            _replace_once(
                values_text,
                "  targetNamespace: sock-shop",
                '  targetNamespace: "sock-shop"',
            ),
            "unsupported value",
        ),
        (
            "values: controller duplicate mapping",
            bootstrap_text,
            values_text + "\ncontrollerManager:\n  targetNamespace: chaos-mesh\n",
            "duplicate key",
        ),
        (
            "values: controller quoted duplicate key",
            bootstrap_text,
            values_text + '\n"controllerManager":\n  targetNamespace: chaos-mesh\n',
            "unsupported key",
        ),
        (
            "values: controller flow mapping",
            bootstrap_text,
            _replace_once(
                values_text,
                "controllerManager:\n",
                "controllerManager: {targetNamespace: sock-shop, "
                "serviceAccountCreate: true}\n",
            ),
            "unsupported value",
        ),
        (
            "values: controller serviceAccountCreate false",
            bootstrap_text,
            _replace_once(
                values_text,
                "  serviceAccountCreate: true",
                "  serviceAccountCreate: false",
            ),
            "serviceAccountCreate",
        ),
        (
            "values: controller serviceAccountCreate missing",
            bootstrap_text,
            _replace_once(values_text, "  serviceAccountCreate: true\n", ""),
            "serviceAccountCreate",
        ),
        (
            "values: controller unknown key",
            bootstrap_text,
            _replace_once(
                values_text,
                "  serviceAccountCreate: true\n",
                "  serviceAccountCreate: true\n  extra: true\n",
            ),
            "unexpected key",
        ),
        (
            "values: rbac create false",
            bootstrap_text,
            _replace_once(values_text, "  create: true", "  create: false"),
            "rbac.create",
        ),
        (
            "values: rbac create missing",
            bootstrap_text,
            _replace_once(values_text, "  create: true\n", ""),
            "rbac",
        ),
        (
            "values: rbac missing",
            bootstrap_text,
            _replace_once(values_text, "rbac:\n  create: true\n\n", ""),
            "rbac",
        ),
        (
            "values: rbac inline flow mapping",
            bootstrap_text,
            _replace_once(
                values_text, "rbac:\n  create: true", "rbac: {create: false}"
            ),
            "unsupported value",
        ),
        (
            "values: rbac unknown key",
            bootstrap_text,
            _replace_once(
                values_text,
                "  create: true\n",
                "  create: true\n  extra: true\n",
            ),
            "unexpected key",
        ),
        (
            "values: dns create true",
            bootstrap_text,
            _replace_once(values_text, "  create: false", "  create: true"),
            "dnsServer.create",
        ),
        (
            "values: dns create missing",
            bootstrap_text,
            _replace_once(values_text, "  create: false\n", ""),
            "dnsServer",
        ),
        (
            "values: dns targetNamespace reintroduced",
            bootstrap_text,
            _replace_once(
                values_text,
                "  create: false\n",
                "  create: false\n  targetNamespace: sock-shop\n",
            ),
            "unexpected key",
        ),
        (
            "values: dns missing",
            bootstrap_text,
            _replace_once(values_text, "dnsServer:\n  create: false\n", ""),
            "dnsServer",
        ),
        (
            "values: unknown top-level key",
            bootstrap_text,
            values_text + "\nfoo: bar\n",
            "unexpected key",
        ),
        (
            "values: tab indentation",
            bootstrap_text,
            _replace_once(
                values_text, "  targetNamespace: sock-shop", "\ttargetNamespace: sock-shop"
            ),
            "tab",
        ),
        (
            "values: odd indentation",
            bootstrap_text,
            _replace_once(
                values_text,
                "  targetNamespace: sock-shop",
                "   targetNamespace: sock-shop",
            ),
            "indentation",
        ),
        (
            "values: deeper nesting",
            bootstrap_text,
            _replace_once(
                values_text,
                "  targetNamespace: sock-shop",
                "  targetNamespace:\n    value: sock-shop",
            ),
            "nested",
        ),
        (
            "values: duplicate rbac.create",
            bootstrap_text,
            values_text + "\nrbac:\n  create: true\n",
            "duplicate key",
        ),
        (
            "values: duplicate dnsServer.create",
            bootstrap_text,
            values_text + "\ndnsServer:\n  create: false\n",
            "duplicate key",
        ),
        (
            "values: duplicate serviceAccountCreate",
            bootstrap_text,
            _replace_once(
                values_text,
                "  serviceAccountCreate: true\n",
                "  serviceAccountCreate: true\n  serviceAccountCreate: false\n",
            ),
            "duplicate key",
        ),
    ]
def _bootstrap_negative_cases(
    bootstrap_text: str, values_text: str
) -> list[tuple[str, str, str, str]]:
    def override(extra: str) -> str:
        return _mutate_chaos_command(
            bootstrap_text,
            "--create-namespace",
            f"--create-namespace {extra}",
        )

    combined_sets = (
        "  --set chaosDaemon.runtime=containerd \\\n"
        "  --set chaosDaemon.socketPath=/run/containerd/containerd.sock "
    )
    return [
        (
            "bootstrap: second --values",
            _mutate_chaos_command(
                bootstrap_text,
                f"--values {VALUES_FILE}",
                f"--values {VALUES_FILE} --values cluster/unsafe-values.yaml",
            ),
            values_text,
            "duplicate",
        ),
        (
            "bootstrap: second -f",
            _mutate_chaos_command(
                bootstrap_text,
                f"--values {VALUES_FILE}",
                f"--values {VALUES_FILE} -f cluster/unsafe-values.yaml",
            ),
            values_text,
            "duplicate",
        ),
        (
            "bootstrap: duplicate approved --values",
            _mutate_chaos_command(
                bootstrap_text,
                f"--values {VALUES_FILE}",
                f"--values {VALUES_FILE} --values {VALUES_FILE}",
            ),
            values_text,
            "duplicate",
        ),
        (
            "bootstrap: --set-json clusterScoped",
            override("--set-json '{\"clusterScoped\":true}'"),
            values_text,
            "--set-json",
        ),
        (
            "bootstrap: --set-json rbac",
            override("--set-json '{\"rbac\":{\"create\":false}}'"),
            values_text,
            "--set-json",
        ),
        (
            "bootstrap: --set-file",
            override("--set-file rbac.create=/tmp/rbac.yaml"),
            values_text,
            "--set-file",
        ),
        (
            "bootstrap: --set-literal",
            override("--set-literal rbac.create=false"),
            values_text,
            "--set-literal",
        ),
        (
            "bootstrap: --post-renderer",
            override("--post-renderer /tmp/render.sh"),
            values_text,
            "--post-renderer",
        ),
        (
            "bootstrap: --set-string",
            override("--set-string rbac.create=false"),
            values_text,
            "--set-string",
        ),
        (
            "bootstrap: --set-json inline",
            override('--set-json={"clusterScoped":true}'),
            values_text,
            "--set-json",
        ),
        (
            "bootstrap: --post-renderer inline",
            override("--post-renderer=/tmp/render.sh"),
            values_text,
            "--post-renderer",
        ),
        (
            "bootstrap: --set-file inline",
            override("--set-file=rbac.create=/tmp/x"),
            values_text,
            "--set-file",
        ),
        (
            "bootstrap: --set-literal inline",
            override("--set-literal=rbac.create=false"),
            values_text,
            "--set-literal",
        ),
        (
            "bootstrap: --set-string inline",
            override("--set-string=rbac.create=false"),
            values_text,
            "--set-string",
        ),
        (
            "bootstrap: clusterScoped override",
            override("--set clusterScoped=true"),
            values_text,
            "clusterScoped",
        ),
        (
            "bootstrap: controller targetNamespace override",
            override("--set controllerManager.targetNamespace=chaos-mesh"),
            values_text,
            "controllerManager.targetNamespace",
        ),
        (
            "bootstrap: dns targetNamespace override",
            override("--set dnsServer.targetNamespace=chaos-mesh"),
            values_text,
            "dnsServer.targetNamespace",
        ),
        (
            "bootstrap: rbac disabled via --set",
            override("--set rbac.create=false"),
            values_text,
            "rbac.create",
        ),
        (
            "bootstrap: serviceAccountCreate disabled via --set",
            override("--set controllerManager.serviceAccountCreate=false"),
            values_text,
            "serviceAccountCreate",
        ),
        (
            "bootstrap: --reuse-values",
            override("--reuse-values"),
            values_text,
            "--reuse-values",
        ),
        (
            "bootstrap: --reuse-values=true",
            override("--reuse-values=true"),
            values_text,
            "--reuse-values",
        ),
        (
            "bootstrap: --reset-values",
            override("--reset-values"),
            values_text,
            "--reset-values",
        ),
        (
            "bootstrap: chart version missing",
            _replace_once(bootstrap_text, "--version 2.8.7 \\\n", ""),
            values_text,
            "version",
        ),
        (
            "bootstrap: chart version wrong",
            _replace_once(bootstrap_text, "--version 2.8.7", "--version 2.8.6"),
            values_text,
            "version",
        ),
        (
            "bootstrap: values file missing",
            _replace_once(bootstrap_text, f"--values {VALUES_FILE} \\\n", ""),
            values_text,
            "values",
        ),
        (
            "bootstrap: values file wrong path",
            _replace_once(
                bootstrap_text,
                f"--values {VALUES_FILE}",
                "--values cluster/other-values.yaml",
            ),
            values_text,
            "values",
        ),
        (
            "bootstrap: release namespace wrong",
            _replace_once(
                bootstrap_text, "--namespace chaos-mesh", "--namespace chaos-other"
            ),
            values_text,
            "namespace",
        ),
        (
            "bootstrap: release name changed",
            _replace_once(
                bootstrap_text,
                f"helm upgrade --install {RELEASE} {CHART}",
                f"helm upgrade --install chaos-other {CHART}",
            ),
            values_text,
            "positional",
        ),
        (
            "bootstrap: chart changed to local path",
            _replace_once(bootstrap_text, CHART, "./cluster/chart"),
            values_text,
            CHART,
        ),
        (
            "bootstrap: runtime setting removed",
            _replace_once(
                bootstrap_text, "  --set chaosDaemon.runtime=containerd \\\n", ""
            ),
            values_text,
            "--set",
        ),
        (
            "bootstrap: socket setting removed",
            _replace_once(
                bootstrap_text,
                "  --set chaosDaemon.socketPath=/run/containerd/containerd.sock ",
                "",
            ),
            values_text,
            "--set",
        ),
        (
            "bootstrap: runtime setting wrong",
            _replace_once(
                bootstrap_text,
                "chaosDaemon.runtime=containerd",
                "chaosDaemon.runtime=docker",
            ),
            values_text,
            "--set",
        ),
        (
            "bootstrap: socket setting wrong",
            _replace_once(
                bootstrap_text,
                "/run/containerd/containerd.sock",
                "/var/run/docker.sock",
            ),
            values_text,
            "--set",
        ),
        (
            "bootstrap: create-namespace false",
            _mutate_chaos_command(
                bootstrap_text, "--create-namespace", "--create-namespace=false"
            ),
            values_text,
            "create-namespace",
        ),
        (
            "bootstrap: create-namespace missing",
            _mutate_chaos_command(bootstrap_text, "--create-namespace ", ""),
            values_text,
            "create-namespace",
        ),
        (
            "bootstrap: wait missing",
            _mutate_chaos_command(bootstrap_text, "--wait ", ""),
            values_text,
            "--wait",
        ),
        (
            "bootstrap: timeout changed",
            _mutate_chaos_command(
                bootstrap_text, "--timeout 10m", "--timeout 5m"
            ),
            values_text,
            "timeout",
        ),
        (
            "bootstrap: extra positional token",
            override("extra"),
            values_text,
            "positional",
        ),
        (
            "bootstrap: install flag missing",
            _mutate_chaos_command(bootstrap_text, "--install", ""),
            values_text,
            "--install",
        ),
        (
            "bootstrap: install false",
            _mutate_chaos_command(
                bootstrap_text, "--install", "--install=false"
            ),
            values_text,
            "--install",
        ),
        (
            "bootstrap: second chaos helm command",
            bootstrap_text
            + f"\nhelm upgrade --install {RELEASE} {CHART} --version 2.8.7\n",
            values_text,
            "multiple",
        ),
        (
            "bootstrap: eval wrapper",
            _replace_once(
                bootstrap_text,
                f"helm upgrade --install {RELEASE} {CHART}",
                f'eval "helm upgrade --install {RELEASE} {CHART}"',
            ),
            values_text,
            "helm upgrade",
        ),
        (
            "bootstrap: unknown flag",
            override("--frobnicate"),
            values_text,
            "unsupported",
        ),
        (
            "bootstrap: missing repository-root cd",
            _replace_once(
                bootstrap_text, 'cd "$(dirname "$0")/.."', "cd ."
            ),
            values_text,
            "cd",
        ),
        (
            "bootstrap: shell separator after command",
            override("; --set clusterScoped=true"),
            values_text,
            "positional",
        ),
        (
            "bootstrap: --namespace=other",
            _replace_once(
                bootstrap_text, "--namespace chaos-mesh", "--namespace=chaos-other"
            ),
            values_text,
            "namespace",
        ),
        (
            "bootstrap: --version=2.8.6",
            _replace_once(
                bootstrap_text, "--version 2.8.7", "--version=2.8.6"
            ),
            values_text,
            "version",
        ),
        (
            "bootstrap: combined --set with clusterScoped",
            _replace_once(
                bootstrap_text,
                combined_sets,
                "  --set chaosDaemon.runtime=containerd,"
                "chaosDaemon.socketPath=/run/containerd/containerd.sock,"
                "clusterScoped=true ",
            ),
            values_text,
            "clusterScoped",
        ),
        (
            "bootstrap: extra non-chaos helm upgrade",
            bootstrap_text
            + "\nhelm upgrade --install extra ./chart --namespace extra\n",
            values_text,
            "exactly two",
        ),
        (
            "bootstrap: monitoring replaced by chaos release",
            _replace_once(
                bootstrap_text,
                "helm upgrade --install monitoring "
                "prometheus-community/kube-prometheus-stack \\\n"
                "  --namespace monitoring --create-namespace \\\n"
                "  --values deploy/monitoring/kps-values.yaml --wait --timeout 10m",
                "helm upgrade --install chaos-mesh ./malicious "
                "--namespace chaos-mesh",
            ),
            values_text,
            "another helm upgrade",
        ),
        (
            "bootstrap: helm install chaos-mesh",
            bootstrap_text + "\nhelm install chaos-mesh ./malicious\n",
            values_text,
            "only the approved",
        ),
        (
            "bootstrap: helm uninstall chaos-mesh",
            bootstrap_text + "\nhelm uninstall chaos-mesh\n",
            values_text,
            "only the approved",
        ),
        (
            "bootstrap: wrapped helm upgrade",
            bootstrap_text
            + '\neval "helm upgrade --install chaos-mesh ./malicious"\n',
            values_text,
            "direct command",
        ),
    ]


def _namespace_negative_cases(
    config_text: str, makefile_text: str, contract_text: str
) -> list[tuple[str, str, str, str, str]]:
    config_line = 'SOCK_NS = os.environ.get("SOCK_NS", "sock-shop")'
    make_line = "SOCK_NS := sock-shop"
    contract_line = "| `SOCK_NS` | `sock-shop` |"
    config_other = 'SOCK_NS = os.environ.get("SOCK_NS", "other")'
    make_other = "SOCK_NS := other"
    contract_other = "| `SOCK_NS` | `other` |"
    return [
        (
            "namespace: config SOCK_NS drift",
            _replace_once(config_text, config_line, config_other),
            makefile_text,
            contract_text,
            "SOCK_NS",
        ),
        (
            "namespace: Makefile SOCK_NS drift",
            config_text,
            _replace_once(makefile_text, make_line, make_other),
            contract_text,
            "SOCK_NS",
        ),
        (
            "namespace: contract SOCK_NS drift",
            config_text,
            makefile_text,
            _replace_once(contract_text, contract_line, contract_other),
            "SOCK_NS",
        ),
        (
            "namespace: config and Makefile drift from contract",
            _replace_once(config_text, config_line, config_other),
            _replace_once(makefile_text, make_line, make_other),
            contract_text,
            "SOCK_NS",
        ),
        (
            "namespace: all sources drift from values",
            _replace_once(config_text, config_line, config_other),
            _replace_once(makefile_text, make_line, make_other),
            _replace_once(contract_text, contract_line, contract_other),
            "targetNamespace",
        ),
        (
            "namespace: config SOCK_NS pattern missing",
            _replace_once(config_text, config_line, 'SOCK_NS = "sock-shop"'),
            makefile_text,
            contract_text,
            "SOCK_NS",
        ),
        (
            "namespace: Makefile SOCK_NS pattern missing",
            config_text,
            _replace_once(makefile_text, make_line, "SOCK_NS ?= sock-shop"),
            contract_text,
            "Makefile",
        ),
        (
            "namespace: contract SOCK_NS pattern missing",
            config_text,
            makefile_text,
            _replace_once(contract_text, contract_line, "| SOCK_NS | sock-shop |"),
            "CONTRACTS.md",
        ),
        (
            "namespace: invalid namespace syntax",
            _replace_once(
                config_text,
                config_line,
                'SOCK_NS = os.environ.get("SOCK_NS", "sock_shop")',
            ),
            _replace_once(makefile_text, make_line, "SOCK_NS := sock_shop"),
            _replace_once(contract_text, contract_line, "| `SOCK_NS` | `sock_shop` |"),
            "valid namespace",
        ),
    ]


def negative_cases(
    bootstrap_text: str, values_text: str
) -> list[tuple[str, str, str, str]]:
    return _values_negative_cases(bootstrap_text, values_text) + _bootstrap_negative_cases(
        bootstrap_text, values_text
    )


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    bootstrap_path = root / BOOTSTRAP_FILE
    values_path = root / VALUES_FILE
    config_path = root / CONFIG_FILE
    makefile_path = root / MAKEFILE_FILE
    contract_path = root / CONTRACT_FILE
    for path in (bootstrap_path, values_path, config_path, makefile_path, contract_path):
        if not path.is_file():
            print(f"SEC-001 guard FAILED: missing {path}")
            return 1

    bootstrap_text = bootstrap_path.read_text(encoding="utf-8")
    values_text = values_path.read_text(encoding="utf-8")
    config_text = config_path.read_text(encoding="utf-8")
    makefile_text = makefile_path.read_text(encoding="utf-8")
    contract_text = contract_path.read_text(encoding="utf-8")

    namespace_errors, sock_ns = check_namespace_sources(
        config_text, makefile_text, contract_text
    )
    errors = (
        namespace_errors
        + check_bootstrap(bootstrap_text)
        + check_values(values_text, sock_ns)
    )
    if errors:
        print("SEC-001 guard FAILED:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("SEC-001 guard: positive case OK")

    positive = positive_variants(CANONICAL_BOOTSTRAP)
    negatives = negative_cases(CANONICAL_BOOTSTRAP, CANONICAL_VALUES)
    namespace_cases = _namespace_negative_cases(
        CANONICAL_CONFIG, CANONICAL_MAKEFILE, CANONICAL_CONTRACT
    )
    if len(positive) != EXPECTED_POSITIVE_VARIANTS:
        print(
            "SEC-001 guard FAILED: expected "
            f"{EXPECTED_POSITIVE_VARIANTS} safe variants, found {len(positive)}"
        )
        return 1
    if len(negatives) != EXPECTED_NEGATIVE_CASES:
        print(
            "SEC-001 guard FAILED: expected "
            f"{EXPECTED_NEGATIVE_CASES} negative cases, found {len(negatives)}"
        )
        return 1
    if len(namespace_cases) != EXPECTED_NAMESPACE_CASES:
        print(
            "SEC-001 guard FAILED: expected "
            f"{EXPECTED_NAMESPACE_CASES} namespace cases, found {len(namespace_cases)}"
        )
        return 1

    failures = 0
    for name, mutated in positive:
        caught = check_bootstrap(mutated)
        if caught:
            failures += 1
            print(f"  NOT ACCEPTED: {name}: {'; '.join(caught)}")
        else:
            print(f"  accepted: {name}")

    for name, mutated_bootstrap, mutated_values, expected in negatives:
        caught = check_bootstrap(mutated_bootstrap) + check_values(
            mutated_values, sock_ns
        )
        if any(expected in error for error in caught):
            print(f"  rejected: {name}")
        else:
            failures += 1
            print(
                f"  NOT REJECTED (expected {expected!r}): {name}: "
                + "; ".join(caught)
            )

    for name, mutated_config, mutated_makefile, mutated_contract, expected in namespace_cases:
        namespace_errors, namespace = check_namespace_sources(
            mutated_config, mutated_makefile, mutated_contract
        )
        caught = namespace_errors + check_values(values_text, namespace)
        if any(expected in error for error in caught):
            print(f"  rejected: {name}")
        else:
            failures += 1
            print(
                f"  NOT REJECTED (expected {expected!r}): {name}: "
                + "; ".join(caught)
            )

    if failures:
        print(f"SEC-001 guard FAILED: {failures} case(s) failed")
        return 1

    total_negative = len(negatives) + len(namespace_cases)
    print(
        "SEC-001 chaos scope offline test OK "
        f"(1 positive, {len(positive)} safe variants, "
        f"{total_negative} negative cases)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
