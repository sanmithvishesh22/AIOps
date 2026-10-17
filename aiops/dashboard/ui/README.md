# aiops/dashboard/ui — React/Vite dashboard UI (D4-003)

The browser surface for the platform: five views — anomaly feed, RCA ranking,
prediction alerts, forecast, remediation queue — over the Contract-E read-only API
(D4-002, one directory up). It is **mock-first**: the default mode renders
hand-written synthetic fixtures with **no backend at all**, so the UI is fully
usable (and testable) before a database or cluster exists. **Live mode is read-only**;
the remediation queue shows audit records but its approve/reject/execute controls are
deliberately disabled — live control is deferred to a future loopback-only control
adapter, documented (design only) in [`../CONTROL_ADAPTER.md`](../CONTROL_ADAPTER.md).

**Status:** D4-003 code complete and offline-tested (`npm test`, `npm run build`, plus
the read-API and D4-001 regressions). Live control and live database integration are
**not implemented / not verified here** — see "Honest limits" at the end.

## Quick start — mock mode (no backend)

```powershell
cd aiops/dashboard/ui
npm install            # React, Vite, Vitest — one lockfile, one package
npm run dev            # http://127.0.0.1:5173 — mock mode by default
```

That is the whole setup: with `VITE_API_MODE` unset the app serves its own fixtures
in-browser, contacts nothing, and every remediation decision is simulated in memory
(see "Mock workflow" below).

## Quick start — live mode (read-only, local read-API)

Live mode talks to the local Express read-API (started from `aiops/dashboard`, see its
[README](../README.md)). The Vite dev server proxies `/api` to the API's default bind,
`http://127.0.0.1:8081`, so the browser only ever calls its own origin — no CORS change
on the API and no secrets or origins in the bundle.

```powershell
# terminal 1 — the read-API (venv active, TIMESCALE_DSN set; see ../README.md)
cd aiops\dashboard ; npm start

# terminal 2 — the UI in live mode
cd aiops\dashboard\ui
$env:VITE_API_MODE = "live"
npm run dev            # still http://127.0.0.1:5173
```

`VITE_API_MODE` is read when the dev server starts (Vite env vars are baked at
start/build time), so restart the server after changing it. The same `/api` proxy is
configured for `npm run preview`.

## Mode semantics (`VITE_API_MODE`)

| Value | Result |
|---|---|
| unset / empty | **mock** — the default for a new local install |
| `mock` | mock — synthetic fixtures in the browser |
| `live` | live — `GET /api/*` through the Vite proxy |
| anything else | a loud, full-page configuration error; **no silent fallback** |

Silently falling back to mock would make synthetic rows look like live data — exactly
the confusion this dashboard must not create — so an unrecognised value stops the UI
instead (`src/api/mode.js`, `src/main.jsx`). The active mode is always visible in the
header ("Mock data" / "Live read-API" badge plus the mode toggle), each mock view
carries a "simulated" marker, and mock remediation rows carry a "Simulated" chip.

## Views

| View | Reads | Notes |
|---|---|---|
| Anomaly feed | `GET /api/anomalies` | flag/score rows, detector metadata, threshold context |
| RCA ranking | `GET /api/rca` | rank 1 = top; carries **"Ranking, not causality."** |
| Prediction alerts | `GET /api/predictions` | breach probability and estimated breach duration |
| Forecast | `GET /api/forecasts` | `forecast_p95` against its two baselines; carries **"Instrument metric, not reliability proof."** |
| Remediation queue | `GET /api/remediations` (live) / in-browser fixtures (mock) | audit records; live controls disabled with the reason stated |

`GET /api/experiments` is **out of D4-003 scope** by instruction — evaluation views
are the separate D4-006 ticket; the read-API endpoint exists and is untouched.

Every view renders four explicit states: **loading**, **empty**, **ready**, **error**.
An empty API answer (`200` with `[]`) is a valid **empty state** ("no data retained"),
never an error and never replaced with sample rows (`src/api/useResource.js`,
`src/components/AsyncBody.jsx`).

## Mock workflow (remediation queue, mock mode)

The mock queue mirrors the D4-001 lifecycle and its audit guard
(`aiops/remediate/audit.py::_TRANSITIONS`) exactly:

```
proposed -> approved | rejected        (one explicit human decision, operator name required)
approved -> applied                    (a separate, explicit execution step)
applied / rejected / failed            (terminal)
```

- Approve/reject and execute are **separate explicit actions** — execution unlocks only
  after an approval, is never automatic, and a rejected action can never execute.
- Duplicate or out-of-order moves are **refused with a visible message** (for example
  deciding an action that is already `approved`).
- An operator name is **required** for approve/reject; it is **self-reported and is not
  authentication** — the UI says so next to the field, and the name only labels this
  browser session.
- Everything is **simulated**: browser memory only, no audit-database write, no
  Kubernetes call. Success and refusal messages say so explicitly ("Simulated: …"),
  and rejected actions stay rejected.

The store (`src/mock/remediationStore.js`) is plain in-memory state created once per
session; switching the header toggle to live mode does **not** carry a mock decision
into live — live mode reads only from the API and shows only server rows (asserted in
`test/mode-boundary.test.jsx`).

## Live mode is read-only by construction

- The only network code is `src/api/live.js`: one `GET` per resource, five endpoints,
  no write path anywhere in the module — there is nothing in the UI that can approve,
  reject, or execute against a server. A source-scanning test asserts that no HTTP
  method other than `GET` is constructed and that only the live adapter touches
  `fetch`.
- In live mode the queue renders disabled controls with the reason
  ("Disabled — live approve, reject, and execute are not enabled in this ticket") and a
  visible note pointing at the deferred control-adapter design. Clicking them sends
  nothing; a test asserts call counts stay unchanged.
- Read failures are **sanitized**: every on-screen message is assembled from the UI's
  own constant strings (`src/api/errors.js` — network / HTTP 400·404·500·503 /
  malformed payload). Nothing from a response body, exception, DSN, or SQL is ever
  forwarded to the DOM — the same rule the Express API already enforces server-side.

## Files

| Path | Role |
|---|---|
| `src/main.jsx` | Entry: parses `VITE_API_MODE`, renders the config-error page or the app |
| `src/App.jsx` | View routing, mode state, client selection, mock-store creation |
| `src/api/` | `mode.js` (parsing), `client.js` (mock/live switch), `live.js` (GET-only fetch), `mock.js`, `errors.js` (sanitized messages), `useResource.js` (four-state hook) |
| `src/mock/` | `fixtures.js` (synthetic Contract-shaped rows), `remediationStore.js` (lifecycle mirror) |
| `src/views/` | The five views (remediation branches: `MockRemediationQueue.jsx` / `LiveRemediationQueue.jsx`) |
| `src/components/` | `Shell` (header/mode/nav), `AsyncBody` (state rendering), list/format helpers |
| `test/*.test.jsx` | Vitest + Testing Library suite |
| `vitest.setup.js` | jest-dom matchers only — at the root, so the Express test run never sees it |

Deliberate non-choices: **no router, no state library, no charting library, no UI
framework** — plain React function components and one stylesheet (29 files under
`src/`, `src/styles.css` included). The five tabs are a `useState` in `App.jsx`;
anything heavier would be a dependency tax this ticket does not need.

## Tests and build (offline — no database, no cluster)

```powershell
cd aiops/dashboard/ui
npm test               # vitest run — 5 files, 55 tests, jsdom
npm run build          # vite build → dist/ (gitignored)
npm run preview        # serve the built bundle on 127.0.0.1
```

The suite covers: mode parsing and the mode boundary (mock contacts no network; live
sends GETs only; a mock decision never leaks to live), the mock lifecycle (explicit
approval, separate execution, refusals for duplicates/invalid moves, required operator
name), rendering and mapping of all five views from mock and live shapes, the
four-state model (loading/empty/ready/error — `[]` is empty, not an error, not sample
data), and the mandatory labels ("Ranking, not causality." / "Instrument metric, not
reliability proof."). Live tests stub `fetch` — nothing here needs a running server.

Test files are `*.test.jsx` **on purpose**: the Express package's `npm test`
(`node --test`) discovers any `.js` under a `test/` directory in `aiops/dashboard`,
but not `.jsx` — so `cd aiops/dashboard && npm test` keeps running only the API suite
and never accidentally executes this one.

## Honest limits (matching the read-API's posture)

- **Not verified here:** live PostgreSQL/TimescaleDB rows through the proxy, and any
  Kubernetes action — there is none. That integration path is INT-003/INT-005; this
  ticket is complete against mocks and the documented shapes.
- **Unauthenticated, localhost-only** by deliberate v1 design, same as the read-API
  (see `SECURITY_AND_ACCESS.md`): the dev server binds `127.0.0.1` and the proxy
  targets `127.0.0.1:8081`. Do not forward either port beyond localhost; any shared
  deployment needs real auth first.
- **No secrets in the bundle:** the UI never reads the DSN or any environment value
  except the build-time `VITE_API_MODE` string; it only ever sees API payloads.
- **The mock's operator name is not identity.** It labels a simulated decision; real
  approvals belong to the audited D4-001 flow with a real `decided_by`. Approval is
  accountability, not safety.
