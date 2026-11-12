"""Backward-compatibility shim. Migrated to aiops.remediation.

All public names are re-exported from aiops.remediation for backward
compatibility. New code should import directly from aiops.remediation.
"""
from aiops.remediation import (  # noqa: F401
    ACTIONS,
    DEFAULT_EXECUTE_TIMEOUT_S,
    DEFAULT_POLL_S,
    InvalidInput,
    RemediateError,
    StateError,
    InMemoryAudit,
    PgAudit,
    FakeK8s,
    RealK8s,
    build_evidence,
    validate_evidence,
    propose,
    approve,
    reject,
    execute,
)

__all__ = [
    "ACTIONS",
    "DEFAULT_EXECUTE_TIMEOUT_S",
    "DEFAULT_POLL_S",
    "InvalidInput",
    "RemediateError",
    "StateError",
    "InMemoryAudit",
    "PgAudit",
    "FakeK8s",
    "RealK8s",
    "build_evidence",
    "validate_evidence",
    "propose",
    "approve",
    "reject",
    "execute",
]