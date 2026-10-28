# Loopback-only control adapter — design note (D4-003 §6)

> **Design only. Nothing here is implemented.** No control adapter process exists, no
> code path in the UI or the read-API can approve, reject, or execute anything, and no
> tests in this repository exercise one. This document records the design the ticket
> asked for so the boundary discussion can happen against something concrete — the
> Contract-E owner must review and agree it before any of it is built.

## Why this note exists

D4-003's honest end state is a **read-only live mode**: the remediation queue shows
audit records from `GET /api/remediations`, and approve/reject/execute are disabled
with the reason stated on screen. The eventual product needs the queue to *drive*
D4-001, which raises the question the ticket requires answering in writing: what would
a minimal live control path look like that does not (a) put a write route on the
read-API, (b) let the browser become an unattended remote control for Kubernetes, or
(c) fork the remediation lifecycle away from its audit guard?

The read-API must stay what Contract E and D4-002 made it: six GET routes,
read-only, loopback-bound, unauthenticated. Adding `POST /api/approve` to it would
break its tests, its contract, and the "no write route is registered" guarantee — so
that is not the design. The design is a **separate process with a separate, narrow
purpose**, living beside the read-API, not inside it.

## Shape

```
browser (live mode, explicit operator action)
   │  POST /control/{approve|reject|execute}      loopback only, its own port
   ▼
control adapter  ── validates → delegates → never re-implements
   │
   ├─► aiops.remediate.approve(store, action_id, decided_by)
   ├─► aiops.remediate.reject(store, action_id, decided_by)
   └─► aiops.remediate.execute(store, k8s, action_id, timeout_s=…, poll_s=…)
           │
           └─► the same audit store / k8s adapters D4-001 already owns
               (remediation_action rows + append-only guard + _TRANSITIONS)
```

- **Separate process, separate port.** Not mounted on the Express read-API, not
  reachable through the Vite `/api` proxy. Its own loopback bind, its own config, its
  own lifecycle. The read-API keeps answering only GETs on `127.0.0.1:8081`.
- **Narrow allowlist — exactly three operations**: `approve`, `reject`, `execute`.
  Nothing else. `propose` is not on the allowlist (proposals come from D4-001 flows
  over real evidence rows, not from a browser form); there is no delete, no
  "set status", no free-form field that could reach a cluster.
- **Delegation, not duplication.** The adapter calls the existing D4-001 functions —
  `aiops.remediate.approve/reject` (which own the `proposed → approved|rejected` gate
  and the "only proposed actions" refusal) and `aiops.remediate.execute` (which owns
  the approval gate, the store row lock that makes double-approval execute exactly
  once, k8s confirmation, and `timeout ≠ success`). The adapter contains **no
  remediation logic of its own**: if D4-001's lifecycle changes, the adapter follows
  or breaks loudly — it can never drift from the audit guard.
- **Audit preservation by construction.** The adapter writes no audit rows itself.
  Every state change it can trigger still goes through D4-001's store and the
  append-only `remediation_action` table with the existing transition guard; failures
  are recorded by the same path (a timed-out execution becomes `failed`, never
  `applied`).

## Request discipline

- **Strict validation, nothing trusted.** JSON body only, small size cap; `action_id`
  must be an integer and must exist; `decided_by` must be a non-empty string for
  approve/reject and is **not accepted** for execute (the decision is already on the
  row); unknown fields are rejected rather than ignored. No request can supply
  cluster parameters — `service`, `action_type`, and `params` are read from the stored
  proposal, so the browser cannot invent a new set of replicas or retarget an action.
- **Bounded execution.** `execute` is accepted only for an `approved` row, exactly
  once — the store's conditional update decides races and the second attempt is a
  refusal, not a second cluster call. The adapter applies an execution timeout
  (D4-001's `timeout_s`/`poll_s` contract): unconfirmed convergence is recorded
  `failed`; a timeout is never reported as success. One in-flight execution per
  action; refusals are cheap and immediate.
- **Sanitized errors.** Responses use a fixed error vocabulary (invalid request /
  unknown action / wrong state / execution failed / internal error) with constant
  bodies. Exception text, k8s messages, DSN/SQL, and stack traces never leave the
  process; details exist only in the adapter's own local log, mirroring the read-API's
  rule. The browser shows the operator only what the vocabulary allows.
- **Explicit human confirmation.** The UI side is unchanged in spirit from mock mode:
  approve/reject and execute remain **separate explicit actions**; a confirmation step
  names the action being changed; controls are disabled while a request is in flight;
  refusal messages are shown verbatim from the vocabulary. No retry is automatic; the
  operator re-initiates.

## Identity, and what it honestly is not

- The operator name is **self-reported**: typed into a field, not authenticated,
  not verified against any directory. Live or mock, it labels accountability; it does
  not prove it. "Approval is accountability, not safety" remains true, and the design
  must not be described as making remediation safe.
- The adapter does **not** solve identity: on a shared machine, anyone with loopback
  access can send the same requests. That is a documented v1 limitation, not an
  oversight — the real fix is D4-009 (auth/RBAC), explicitly out of scope for v1.
  Until then the adapter's honest claim is: *an explicitly confirmed, audited,
  bounded human action from a loopback-only UI*, nothing stronger.

## Loopback and its limits (the part that needs owner judgment)

- Loopback is a **bind, not a boundary for the whole path**. Anything that can reach
  localhost can reach the adapter: other local users/processes, an SSH tunnel, a
  port-forward, or a reverse proxy in front of it. The design must therefore assume
  no network is safe and keep the allowlist and validation as the last line — and the
  README-level warning stays: **do not forward the control port beyond localhost.**
- A browser-origin hazard applies to a localhost HTTP service: other web pages on the
  same machine can attempt requests to loopback. The design needs defenses chosen
  with the owner — e.g. requiring a custom header the CORS rules will not let a
  cross-origin page send, an explicit `Origin`/`Host` check, and **no CORS headers at
  all** — rather than relying on "it's only loopback". Which combination is sufficient
  is a review question, not a settled detail.
- The adapter should be **off unless explicitly started**, bind a literal loopback
  constant (no host override, same pattern as `src/config.js` in the read-API), and
  log one fixed startup line. Enabling it is a deliberate operator act.

## Required tests before implementation is accepted

Written against mocks (mock k8s + mock store), in the same offline style as D4-001 and
D4-002:

1. Allowlist: exactly `approve`/`reject`/`execute` are routable; everything else
   (including `propose`, any `/api`-style path) is absent/404; no write keyword can
   reach a non-control path.
2. Validation: non-integer/unknown `action_id` → invalid-request; missing/blank
   `decided_by` for approve/reject → invalid-request; `decided_by` or `params` on
   execute → invalid-request; oversized/unknown-field bodies refused.
3. State refusals: execute without approval → refused, **no k8s call**; reject after a
   decision → refused; duplicate approve → refused; double-approval of the same action
   executes exactly once (reuse D4-001's selftest assertions).
4. Timeout ≠ success: an execution whose convergence never confirms is stored
   `failed`, never `applied`.
5. Audit shape: rows produced through the adapter are byte-identical in shape to rows
   produced by calling D4-001 directly; the append-only guard still refuses
   illegal transitions attempted through any path.
6. Sanitization: error bodies never contain DSNs, SQL, stack traces, k8s messages, or
   row contents; logs contain no request payloads.
7. Listener: binds loopback only; refuses non-loopback addresses; no host option can
   widen it; origin/header defenses behave as specified.
8. UI: live approve/reject/execute stay disabled until the adapter is explicitly
   enabled and configured; mode switching cannot re-send a stored action; every
   control path shows the confirmation step.

## Open questions for the owner (before any code)

- **Contract-E boundary:** does live control require a new, explicit contract (and
  README/security documentation), and who owns it? This note takes no position —
  it exists so that decision is made deliberately.
- Is `propose` expected to ever be browser-initiated, or does it stay server-side
  only? (The design above deliberately excludes it.)
- Which loopback-origin defense is the required minimum (header + origin check vs
  more), given the local-only threat model?
- Should the adapter share D4-001's store/k8s wiring directly, or run in the same
  process family as the Python bridge for a single config source?
- Relationship to D4-008 (autonomous allowlist + rollback): distinct tickets, same
  boundary questions; whichever lands first must not weaken the other's guarantees.

**Gate:** owner review of this note, and of any Contract-E extension it implies, is a
precondition for implementation. Until then, the delivered UI stays exactly what
D4-003 asked for: fully functional against mocks, read-only against live data, with the
controls disabled and the reason on screen.
