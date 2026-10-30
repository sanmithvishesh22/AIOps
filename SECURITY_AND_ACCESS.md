# Security & Access Document
## AIOps Platform — for a future hosted, multi-user version

**Owner:** Sanmith
**Status:** Forward-looking design — **not built in v1**
**Audience:** Founder / non-technical reader (plain English throughout)
**Governing baseline:** `LITERATURE_SURVEY_DECISION_REPORT.md`. If anything here ever conflicts with a research claim, the survey wins.

---

## 0. Read this first — what this document is, and what it is not

Today, the AIOps platform is a **single-person research tool** that runs on your own laptop's local cluster. On purpose, it has **no login, no user accounts, and no passwords**, and it is reachable only from your own machine (this is written down in `PRD.md` §8 and `TECHNICAL_ARCHITECTURE.md` §10). For a tool that only you can reach on your own computer, that is a reasonable and deliberate choice — adding logins to it now would be effort spent guarding a door that only you can walk through.

**This document describes something different:** the security model the platform *would* need **if you ever turned it into a hosted product** that other people — and eventually other companies — log into over the internet. Think of it as the blueprint you pull out the day you decide "other people are going to use this." Everything below is a **target design**, not a description of what exists today. Nothing here is built yet.

I'm writing it now because the cheapest time to decide how access will work is *before* you have customers, not after. One honest caveat, in keeping with the project's ground rules: the controls below **reduce and account for risk** — they do not make any action "safe" in an absolute sense. A human approving an automated fix, for example, gives you accountability and a chance to catch mistakes; it does not guarantee the fix is harmless.

---

## 1. The whole model in one paragraph

When the platform becomes a hosted product, each **company** that uses it is a "tenant" — a sealed box. People log in using their existing company sign-in (Google, Microsoft, Okta — whatever they already use), so you never store passwords. Once logged in, what each person can *see and do* depends on their **role** (a viewer sees dashboards; an operator can approve fixes; an admin manages the team). The **database itself** enforces the sealed boxes: it will physically refuse to return one company's data to another company, even if the app code has a bug. Every sensitive action — especially approving a fix that changes live infrastructure — is **logged, permanently, with who did it and when**. And when things break (a data source goes down, a fix fails to apply), the system **fails safely**: it never pretends everything is healthy, and it never changes infrastructure it isn't sure about.

---

## 2. Authentication — how people prove who they are

**Recommendation: sign in with the company's existing identity provider (SSO), using the OpenID Connect / OAuth 2.0 standard — do not build your own username-and-password system.**

In plain English, "SSO" (single sign-on) means: when someone opens the platform, they click "Sign in with Google" (or Microsoft, or Okta), authenticate on *their* company's system, and get bounced back to you already logged in. You never see or store their password.

Why this is the right fit for *this* product specifically:

- **Your users are engineers inside companies.** They already have a corporate login with the security team's rules baked in. Reusing it is less work for you and safer for them.
- **You never hold passwords.** The single most common early-stage breach is a leaked password database. If you don't store passwords, you can't leak them.
- **Offboarding is automatic.** When an employee leaves and their company disables their account, they instantly lose access to your platform too — you don't have to remember to remove them.
- **You inherit multi-factor authentication (MFA) for free.** If their company requires a second factor (a phone tap, a code), that protection extends to your platform without you building anything.
- **Enterprise buyers will require it.** "Do you support SSO?" is one of the first questions any company's security review asks. Having it removes a sales blocker.

The pieces you'll actually implement:

- **Short-lived access tokens.** After login, the user's browser holds a small, temporary pass (a "token") that expires quickly — think minutes to an hour — and is silently renewed while they stay active. Short lifetimes mean a stolen token is useless within minutes.
- **Multi-factor authentication, required for anyone who can approve a fix.** Viewing dashboards can be single-factor; *approving a change to live infrastructure* should always demand a second factor. High-power actions get higher-assurance sign-in.
- **Step-up authentication for the most dangerous actions.** Even an already-logged-in operator should be re-prompted (re-confirm identity) right before something destructive, like restarting a service or shifting live traffic.
- **Service accounts for the machines, not people's logins.** The platform's own background programs — the parts that read metrics and write results — authenticate with their own scoped machine credentials, never a human's login. If a person leaves, the machines keep running; if a machine key leaks, it can be rotated without touching any human account.

**What to avoid:** building your own email-and-password system, storing passwords yourself, long-lived tokens that never expire, or a single shared admin login for the whole team (you lose all ability to tell who did what).

---

## 3. User roles — who can do what

Everyone belongs to exactly one company (tenant) and has one role inside it. Roles are about *what a person is allowed to do*, and they matter most around one action: **approving an automated fix**, because that changes live infrastructure. Below, "✅" means allowed, "❌" means blocked.

| Capability (plain English) | Viewer / Auditor | Manager | Operator (SRE) | Org Admin |
|---|:--:|:--:|:--:|:--:|
| See dashboards, anomalies, root-cause views, forecasts | ✅ | ✅ | ✅ | ✅ |
| See SLO reports and cost/spend figures | ✅ | ✅ | ✅ | ✅ |
| See the permanent audit log of past actions | ✅ | ✅ | ✅ | ✅ |
| **Approve or reject an automated fix** (scale, restart, traffic shift) | ❌ | ❌ | ✅ | ✅ |
| Change SLO targets and experiment settings | ❌ | ❌ | ✅ | ✅ |
| Invite / remove users, change people's roles | ❌ | ❌ | ❌ | ✅ |
| Manage billing, integrations, and company settings | ❌ | ❌ | ❌ | ✅ |
| Export the company's data | ❌ | ✅ | ✅ | ✅ |
| See raw secrets/credentials (API keys, tokens) | ❌ | ❌ | ❌ | ❌ *(no one — see below)* |

In words:

- **Viewer / Auditor** — can look at everything (including the audit log, which is why it's good for a compliance reviewer) but cannot change or approve anything. A safe "read-only" seat.
- **Manager** — the same visibility plus the ability to export reports, but still **cannot approve fixes or change settings**. This is the "owns the outcomes and the budget, but doesn't push the buttons" seat.
- **Operator (SRE)** — the hands-on role: approves or rejects fixes, tunes SLO targets and experiments. This is the only non-admin role that can touch live infrastructure, and it's the role that must have MFA.
- **Org Admin** — everything an operator can do, plus managing people, billing, and company settings. Keep the number of admins small.

Two rules that sit above the table: **nobody — not even an admin — can read stored raw secrets through the interface** (they can rotate a key, but never display it), and **the audit log can never be edited or deleted by anyone**, because a log you can quietly change is worthless as evidence.

---

## 4. Row-level security — the database's own locks

**Row-level security (RLS)** means the database itself decides which *rows* (individual records) each user is allowed to see or change — not the app code, the database. It's a second lock *behind* the application. Even if a bug in the app accidentally asks for the wrong data, the database refuses to hand it over. For a product where the whole promise is "your company's data stays yours," this is the control that actually keeps that promise.

Because the platform stores its data in PostgreSQL/TimescaleDB, RLS is a built-in feature — you switch it on per table and write the rules once. Here are the rules, in plain English, applied to the tables the platform already has (`inference` — every module's results; `experiment_run` / `experiment_result` — the test records; `remediation_action` — the fix-approval audit log):

1. **Tenant isolation (the big one).** Every record gets stamped with a `tenant_id` — which company it belongs to. The rule: *a user can only ever see or touch records whose `tenant_id` matches their own company.* This is enforced on every table, for every read and every write. One company physically cannot reach another's data, full stop. This single rule is what makes the "sealed box" real.

2. **Read-only means read-only, in the database.** A Viewer's or Manager's connection is only permitted to *read* rows — the database rejects any attempt to insert, change, or delete, regardless of what the app tries. So a mistaken button or a compromised page still can't write anything.

3. **Approving a fix is a privileged write.** Only Operator and Admin roles are allowed to create or update rows in the `remediation_action` table (that's what "approving a fix" is under the hood). Everyone else can *read* those rows (to see history) but never create or change them.

4. **The audit log is append-only.** Rows in `remediation_action` can be *added* and can move forward through their status (proposed → approved → applied), but **no role is ever allowed to delete them or rewrite their history**. The database enforces the immutability, so the record of who approved what is trustworthy.

5. **Machines write, but stay in their lane.** The platform's own background programs use a service account that may *insert* results into `inference` for its own tenant — and nothing more. It cannot read the remediation decisions or touch other tenants. If that machine key ever leaked, the blast radius is "can write junk metrics for one tenant," not "can read everyone's data."

6. **(Optional, finer-grained) team or service ownership.** Within one company you can go a step further — e.g., an operator on the "payments" team can only approve fixes for payments' services. This is an extra `WHERE the service belongs to the user's team` condition layered on top of tenant isolation. Add it only when a customer is big enough to need it; tenant isolation alone is enough to launch.

The mental model: **rule #1 keeps companies apart, rules #2–#5 keep roles honest, and rule #6 is there when a single company gets large.**

---

## 5. Error handling guide — what happens when things break

One principle runs through all of this: **fail closed on anything that changes infrastructure or grants access; fail soft (degrade gracefully) on anything that only displays information.** And in every case, the user sees a plain, friendly message while the technical detail goes to your private server logs — never leak internal errors, stack traces, or "account not found" hints to the screen, because those help attackers.

Here are the major failure points and the right behavior for each:

| Where it breaks | What the user should see | What the system should do |
|---|---|---|
| **Login / SSO fails** (wrong account, expired session, identity provider down) | "We couldn't sign you in — please try again." Never reveal whether an email exists. | Fail closed (no access). Retry against the provider; if it's down, deny entry rather than guess. |
| **Permission denied** (a role tries something it can't) | "You don't have permission to do that." | Block the whole action — never do half of it. Log the attempt with who tried. |
| **Metrics source (Prometheus) unreachable** | A banner: "Live telemetry is temporarily unavailable — showing last known data from HH:MM." | Keep serving last-known data clearly marked as stale. Retry with backoff. **Never show an empty screen as if everything is healthy.** |
| **Results database (TimescaleDB) down or slow** | "Some data is delayed." Dashboards degrade, they don't crash. | Reads serve cached/last-known with a staleness note; writes are queued or dropped-with-a-logged-warning (pick one and be consistent). |
| **A fix fails to apply** (the Kubernetes call errors or times out) | "This action did not complete — no changes were made / changes are being verified." | Mark the action **failed** in the audit log, alert the operator, and **never mark it "applied" unless the change is confirmed.** Retries must be safe to repeat. |
| **Two operators approve at once / the same fix is approved twice** | The second person sees "This action was already handled." | The action executes **exactly once**; the status lifecycle blocks duplicates. |
| **Bad or malformed data arrives** (a module sends an incomplete result) | (Not user-facing.) | Reject the record loudly and log it — **do not silently store blanks**, which would corrupt later analysis. (This matches how the platform already behaves.) |
| **Invalid settings entered** (e.g., a negative replica count, an impossible SLO) | "That value isn't allowed — please enter a number between X and Y." | Reject before saving. Scaling limits are enforced on the server, never trusted from the screen alone. |
| **Too many requests / overload** | "You're going too fast — please wait a moment." | Rate-limit politely (a "429" response). Protect the database and the infrastructure API from being stampeded. |
| **An outside integration fails** (alerting, SSO webhook) | Usually invisible to the user. | Degrade gracefully, queue the work, and notify an admin — one broken integration must not take the whole platform down. |

The through-line: **displaying data can be best-effort; changing infrastructure or granting access must be certain-or-refuse.**

---

## 6. Edge cases to handle before launch

These are the "obvious in hindsight" situations that cause real incidents. Group by group:

**Accounts & access**

- **Instant offboarding.** When someone's company account is disabled, they must lose access within minutes, not hours — this is why access tokens are short-lived.
- **Don't let the org lock itself out.** The last remaining admin can't be allowed to delete or demote themselves; every company must always have at least one admin.
- **One person, multiple companies.** A consultant may belong to two tenants. Switching between them must never leak one company's data into the other's view.
- **Role changes take effect immediately.** If an admin downgrades an operator to viewer mid-session, the operator should lose the ability to approve fixes right away, not at their next login.

**Data & tenancy**

- **A brand-new, empty company.** With no data yet, show a friendly "let's get you set up" screen — not error messages or a broken dashboard.
- **A very large company.** Thousands of services means dashboards and database rules must stay fast; enforce pagination and query limits so one big tenant can't slow everyone down.
- **Deleted services with history.** If a service is removed, its past records in the audit log must remain readable — deleting the service must not break old history.
- **Secrets must never appear in logs or on screen.** Scrub tokens, keys, and passwords out of server logs and out of the evidence shown next to a proposed fix.
- **Data export and deletion.** A company must be able to export its own data and, if it leaves, have its data deleted — and both must respect the sealed-box boundary.

**Fixes & infrastructure safety** *(the highest-stakes group for this product)*

- **⚠️ Never let experiment/fault-injection tools point at real customer infrastructure.** The platform uses fault injection (Chaos Mesh) to *test* itself. In a hosted product this capability must be hard-walled off from any real customer environment — deliberately breaking a customer's live services would be catastrophic. Treat "can fault-injection reach production?" as a launch-blocking checklist item.
- **Stale approvals.** A fix approved five minutes ago may no longer make sense if the problem already cleared. Re-check the situation right before applying, and expire approvals that sit too long.
- **Runaway scaling ("denial of wallet").** A bad forecast could tell the system to add hundreds of replicas and run up a huge bill. Enforce maximum limits on the server — never trust the limit to come from the screen.
- **Confirm before claiming success.** An action is only "done" when the change is verified in the cluster; a timeout is *not* a success.

**Operations & lifecycle**

- **Clock skew.** The app, the database, and the cluster must agree on time, or breach windows and token expiries drift and misbehave.
- **Rotating keys without downtime.** You must be able to replace a leaked or expiring credential while the platform keeps running.
- **Backups keep the boundaries.** A restored backup must preserve both tenant isolation and the audit log's can't-be-edited property — a backup is not a loophole around your own rules.

---

## 7. Where to start (so this isn't overwhelming)

If and when you productize, build the security in this order — each step is useful on its own:

1. **SSO login + short-lived tokens** — the front door. Nothing else matters until people log in properly.
2. **Tenant isolation via database row-level security** — the sealed box. Do this *before* your second customer, never after.
3. **The four roles + the "only operators approve fixes" rule** — the day-to-day guardrail.
4. **The append-only audit log with MFA on approvals** — accountability for the one action that changes live infrastructure.
5. **The error-handling behaviors and edge cases above** — hardening, folded in as you go.

Everything here is the *destination*. Today's local research tool doesn't need any of it, and building it now would be guarding an empty room. Keep this document as the plan for the day the room fills up.

---

*This document is a forward-looking security design for a hypothetical hosted, multi-user version of the platform. It is not implemented in v1, which is an unauthenticated, localhost-only single-user research instrument by design (`PRD.md` §8, `TECHNICAL_ARCHITECTURE.md` §10). It conforms to `LITERATURE_SURVEY_DECISION_REPORT.md`; the controls described reduce and account for risk rather than making any action absolutely safe.*
