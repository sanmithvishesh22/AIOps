# AIOps platform — one-liners. Run on your Mac (needs docker, kind, kubectl, helm).
.DEFAULT_GOAL := help
CLUSTER := aiops
SOCK_NS := sock-shop
PY_MODULES := ingest detect rca explain predict forecast scaler remediate dashboard

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

up: ## create cluster + install testbed (Sock Shop, Prometheus, Chaos Mesh, our components)
	bash cluster/bootstrap.sh

down: ## delete the whole cluster
	kind delete cluster --name $(CLUSTER)

deploy: ## re-apply just our components (after code/manifest changes)
	@out="$$(kubectl kustomize deploy/platform/overlays/local)" || exit $$?; \
	if [ -n "$$out" ]; then echo "$$out" | kubectl apply -f -; \
	else echo "no platform module manifests yet — nothing to deploy"; fi

platform-image: ## build the shared aiops:dev image and load it into the kind cluster
	CLUSTER=$(CLUSTER) bash cluster/platform-image.sh

load: ## run a k6 load Job against Sock Shop (REGIME=stationary|diurnal|spike|bursty)
	@REGIME=$${REGIME:-stationary}; \
	python3 -m experiment.load --manifests "$$REGIME" | kubectl apply -f -

chaos: ## list chaos experiments (render: python3 -m experiment.faults --render <name>)
	@python3 -m experiment.faults --list

security-test: ## run the SEC-001 Chaos Mesh namespace-scope guard (offline)
	python3 cluster/chaos_scope_offline_test.py

selftest: ## run every module's offline self-check (no cluster needed)
	@for m in $(PY_MODULES); do \
		echo "== aiops.$$m =="; python3 -m aiops.$$m --selftest || exit 1; done
	@echo "== aiops.common.store =="; python3 -m aiops.common.store --selftest || exit 1
	@echo "== aiops.common.fixtures =="; python3 -m aiops.common.fixtures --selftest || exit 1
	@echo "== aiops.common.prom =="; python3 -m aiops.common.prom --selftest || exit 1
	@echo "== aiops.ingest_csv =="; python3 -m aiops.ingest_csv --selftest || exit 1
	@echo "== experiment.schema (offline) =="; python3 experiment/schema_offline_test.py || exit 1
	@echo "== cluster.chaos_scope (SEC-001) =="; python3 cluster/chaos_scope_offline_test.py || exit 1
	@echo "== experiment.load =="; python3 -m experiment.load --selftest || exit 1
	@echo "== experiment.faults =="; python3 -m experiment.faults --selftest || exit 1
	@echo "== experiment.runner =="; python3 -m experiment.runner --selftest || exit 1
	@echo "== experiment.analysis =="; python3 -m experiment.analysis --selftest || exit 1
	@echo "== experiment.audit (QA-003) =="; python3 experiment/audit.py || exit 1
	@echo "== experiment.metric_gate (QA-004) =="; python3 experiment/metric_gate.py || exit 1

schema-test: ## apply schema + prove the append-only audit guard (needs a reachable Postgres)
	psql "$${TIMESCALE_DSN:-postgresql://aiops:aiops@localhost:5432/aiops}" -v ON_ERROR_STOP=1 \
		-f experiment/schema.sql -f experiment/schema_test.sql

ps: ## what's running
	kubectl get pods -A | grep -E 'sock-shop|monitoring|chaos-mesh|aiops' || true
