# Developer 2 — Tickets
## Diagnosis Pipeline (Detect · RCA · Explain)

**Mission:** Say what's wrong, rank why, and explain the flag — all offline-testable, never touching infrastructure control. Your stream never blocks the contribution.

**How to use this file (prepend to every AI prompt below):**
> You are in the `aiops-platform` monorepo. Read `ARCHITECTURE.md`, `TECHNICAL_ARCHITECTURE.md`, and `PARALLEL_DEV_PLAN.md` first. Rules: reuse `aiops/common/{prom,store,config}.py` (import, never re-implement); read config from env vars only; every module ships an offline `python -m aiops.<module> --selftest` (assert-based, no framework, no cluster) as its only test; edit only files inside your owned directories; never surface the retired claims ("first integrated platform", "integration is novel", "forecast accuracy proves reliability", "RCA proves causality", "human approval makes remediation safe", "Sock Shop generalizes to production"); keep it minimal — no speculative abstractions.

**Files you own:** `aiops/detect/*`, `aiops/rca/*`, `aiops/explain/*`, `requirements-{detect,rca,explain}.txt`.

**Files to avoid:** `aiops/common/*` (import only — request changes from Dev 1); the dashboard (Dev 4 renders your rows, you just write them); Dev 3's forecasting/experiment tree.

**Contracts you must honor:** write only the documented `kind` values via `store.py` — detect: `anomaly_score`, `anomaly_score_seq`, `anomaly_flag`; rca: `culprit_rank`; explain: `attribution`. Consume the Contract-C feature frame (build against Dev 1's `sample_frame()` until the live bridge lands). Read Prometheus only through `prom.py`.

**Guardrail that lives in your stream:** RCA output is a **ranking, not causal proof** — say so in every output and code comment (D2-004).

---

### D2-001 — Isolation Forest + severity gate · **Must** · deps: D1-001 (fixture) · Phase 1
**Build:** per-service unsupervised detector over the feature frame; severity gate suppresses low-score noise.
**Done when:** on `sample_frame()`, flags injected outliers; gate suppresses low-score noise; `--selftest` green.
**Prompt:**
> In `aiops/detect/`, build a per-service Isolation Forest over the Contract-C frame; add a severity gate that suppresses low-score noise. Write `anomaly_score` (∈[0,1]) and `anomaly_flag` rows via `store.py` with `meta={detector,threshold,features}`. `--selftest` on `sample_frame()` must flag injected outliers and pass the severity gate.

### D2-002 — LSTM autoencoder · **Must** · deps: D1-001 · Phase 1
**Build:** temporal detector scoring reconstruction error; writes `anomaly_score_seq`.
**Done when:** trains offline on the fixture; `--selftest` asserts higher error on anomalous windows.
**Prompt:**
> Add a PyTorch LSTM autoencoder in `aiops/detect/` scoring reconstruction error over windowed sequences; write `anomaly_score_seq`. Train offline on the fixture. `--selftest` asserts higher error on anomalous windows. Put torch in `requirements-detect.txt`.

### D2-003 — Service dependency graph · **Must** · deps: D1-001 · Phase 1
**Build:** directed service graph built at runtime from traces/metrics (not modeled in the DB).
**Done when:** produces a directed graph from sample traces; deterministic given the fixture.
**Prompt:**
> In `aiops/rca/`, build a directed service dependency graph at runtime from Sock Shop traces/metrics (do NOT model it in the DB). Deterministic given a fixture. `--selftest` asserts expected edges.

### D2-004 — Propagation & culprit ranking · **Must** · deps: D2-001, D2-003 · Phase 1
**Build:** rank services by severity + graph propagation; writes `culprit_rank`. **Ranking, not causal proof.**
**Done when:** on a seeded incident the injected culprit ranks #1 on the fixture; output labeled "ranking, not causality".
**Prompt:**
> In `aiops/rca/`, rank services by severity + graph propagation; write `culprit_rank` (1=top) with `meta={score,incident_id,graph_edges}`. Every output and code comment must state "ranking, not causal proof". `--selftest`: on a seeded incident the injected culprit ranks #1.

### D2-005 — SHAP/LIME explainability · **Must** · deps: D2-001 (predict soft) · Phase 1
**Build:** attributions over the detector (and predictor rows when present); writes `attribution`.
**Done when:** returns top-k feature weights for a flagged anomaly; degrades gracefully if predictor rows absent; `--selftest` green.
**Prompt:**
> In `aiops/explain/`, compute SHAP (fallback LIME) attributions over the detector (and predictor rows when present); write `attribution` with `meta={target_module, shap}`. Degrade gracefully if predictor rows are absent. `--selftest` returns top-k weights for a flagged anomaly. shap in `requirements-explain.txt`.

### D2-006 — Ensemble voting + confidence · **Should** · deps: D2-001, D2-002 · Phase 4
**Build:** blend IF + LSTM-AE into one score + confidence.
**Done when:** blended score improves separation on the fixture vs either alone; confidence field populated.
**Prompt:**
> Blend IF + LSTM-AE into one score + confidence in `aiops/detect/`. `--selftest` shows better outlier separation than either alone on the fixture.

### D2-007 — NL explanation summaries · **Nice** · deps: D2-005 · Phase 4
**Build:** plain-language one-liner per flag from attributions.
**Done when:** non-empty human-readable summary per flag; no new heavy deps.
**Prompt:**
> Turn attributions into a plain-language one-liner per flag. No new heavy deps. `--selftest` asserts a non-empty summary string.

---

## QA you contribute to

### QA-004 (detect half) — Detector quality gate · **Must** · Phase 3
False-positive rate bounded on the fixture/live data; document that this is an **instrument-quality metric, not reliability proof**.

---

**Definition of done (Dev 2):** all three modules deploy as kustomize components, write correct `kind` rows to `inference`, pass `--selftest`, and appear in the dashboard once Dev 4 wires the read-API — with zero edits to any file outside `aiops/{detect,rca,explain}`.
