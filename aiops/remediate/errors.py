"""Remediation error types — small on purpose.

- InvalidInput: a workflow call got malformed/insufficient input (bad action_type,
  params, evidence, or an anonymous decided_by) — fail loudly *before* anything is
  stored or executed.
- StateError: the requested operation does not match the action's lifecycle state
  (not 'proposed' to decide, not 'approved' to execute, already handled, unknown).
"""
from __future__ import annotations


class RemediateError(Exception):
    """Base for every remediation workflow error."""


class InvalidInput(RemediateError):
    """Malformed or insufficient input to a workflow call."""


class StateError(RemediateError):
    """The action is not in the state this operation requires."""
