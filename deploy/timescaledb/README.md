# TimescaleDB Local Testbed Deployment (`deploy/timescaledb`)

This directory provides the local-Kubernetes deployment manifests for TimescaleDB on the kind testbed. TimescaleDB serves as the structured storage plane for the AIOps platform, backing ML inference results (Contract A) and paired-experiment relational records (Contract D).

## Manifest Resources

The Kustomization (`deploy/timescaledb/kustomization.yaml`) deploys the resources defined in `deploy/timescaledb/resources.yaml`:

| Object | Name | Namespace | Description |
|---|---|---|---|
| `Namespace` | `aiops` | — | Platform namespace holding our operational components. |
| `Secret` | `timescaledb` | `aiops` | Opaque secret providing `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` as environment variables. |
| `Service` | `timescaledb` | `aiops` | ClusterIP service exposing port `5432` to the cluster (DNS: `timescaledb.aiops:5432`). |
| `StatefulSet` | `timescaledb` | `aiops` | Single replica (`replicas: 1`) running image `timescale/timescaledb:2.17.2-pg16`. |

### Storage & Probes
* **Storage Volume:** The StatefulSet requests a 2Gi PersistentVolumeClaim (`volumeClaimTemplates` name `data`, access mode `ReadWriteOnce`) mounted at `/var/lib/postgresql/data` with subPath `pgdata`.
* **Readiness Probe:** Runs `pg_isready -U aiops` (initial delay 10s, period 5s).

## Credential Convention

The deployment uses the explicit local demo credentials defined in `deploy/timescaledb/resources.yaml`:
* **User:** `aiops`
* **Password:** `aiops`
* **Database:** `aiops`

> [!IMPORTANT]
> These credentials are for the ephemeral local kind testbed only. They match the defaults in `aiops/common/config.py` (`postgresql://aiops:aiops@timescaledb.aiops:5432/aiops`), `Makefile` (`postgresql://aiops:aiops@localhost:5432/aiops`), and `docs/CONTRACTS.md` (Contract G). Never use or expose demo credentials in production environments.

## Storage Architecture & Schema Division

The repository divides data into two distinct database layers:

1. **Inference Store (Contract A — ML Hot Path):**
   * Table: `inference(ts, module, service, kind, value, meta JSONB)` plus index `inference_lookup`.
   * **Initialization:** Initialized programmatically by application code calling `aiops.common.store.init()`.
   * `store.init()` issues idempotent `CREATE TABLE IF NOT EXISTS` and `SELECT create_hypertable('inference', 'ts', if_not_exists=>TRUE);`.
   * **Scope:** `store.init()` initializes **only** the `inference` hypertable. It **does not** create or manage the relational experiment tables in `experiment/schema.sql`.

2. **Experiment Relational Schema (Contract D — Relational Ledger):**
   * Tables: `experiment_run`, `experiment_result` (1:1 with CASCADE), and `remediation_action` (with `remediation_audit_guard` trigger).
   * DDL definition: [`experiment/schema.sql`](../../experiment/schema.sql).

## Schema Application: Current Status & Gap

* **No Automated Mount:** `deploy/timescaledb/resources.yaml` does not mount `experiment/schema.sql` into `/docker-entrypoint-initdb.d/`. Deploying the manifests via `kubectl apply -k deploy/timescaledb` starts an empty TimescaleDB container without Contract D relational tables.
* **Bootstrap Behavior:** `cluster/bootstrap.sh` runs `kubectl apply -k deploy/timescaledb`, but does not execute a schema application command.
* **Manual / Test Execution via Makefile:**
  The `Makefile` defines the `schema-test` target:
  ```bash
  make schema-test
  ```
  Implementation:
  ```makefile
  psql "${TIMESCALE_DSN:-postgresql://aiops:aiops@localhost:5432/aiops}" -v ON_ERROR_STOP=1 \
      -f experiment/schema.sql -f experiment/schema_test.sql
  ```
  `make schema-test` applies `experiment/schema.sql` and immediately runs `experiment/schema_test.sql` to verify constraints and trigger enforcement. It is an end-to-end schema verification check against a reachable database.
* **Port Mapping & In-Cluster Connectivity:**
  `cluster/kind-config.yaml` maps ports `8080`, `3300`, and `9090` to localhost, but does **not** map TimescaleDB port `5432` to the host by default. To run `make schema-test` from the host machine against the kind cluster, you must either:
  1. Forward the port: `kubectl port-forward -n aiops svc/timescaledb 5432:5432`
  2. Or configure `TIMESCALE_DSN` to point to a reachable PostgreSQL/TimescaleDB endpoint.
* **Procedure Gap:** An automated in-cluster mechanism (e.g. ConfigMap mount in `resources.yaml` or an explicit step in `cluster/bootstrap.sh`) to initialize `experiment/schema.sql` on fresh cluster bring-up has not been implemented. This remains a known gap to confirm and document during live cluster integration.

## Verification Matrix

* **Offline Static Verification:**
  * Static schema linting: `python experiment/schema_offline_test.py` validates `experiment/schema.sql` syntax, columns, and trigger DDL offline without requiring a database.
  * Store module selftest: `python -m aiops.common.store --selftest` validates `aiops.common.store` logic, loud KeyError isolation, and hypertable DDL using mock psycopg2.
* **Live Verification (Requires Running Cluster & Tools):**
  * Manifest deployment: `kubectl apply -k deploy/timescaledb` requires Docker, kind, and kubectl.
  * Relational schema & trigger test: `make schema-test` requires a reachable TimescaleDB instance and `psql`.
