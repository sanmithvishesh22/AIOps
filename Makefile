# AIOps platform — one-liners. Run on your Mac (needs docker, kind, kubectl, helm).
.DEFAULT_GOAL := help
CLUSTER := aiops
SOCK_NS := sock-shop

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

up: ## create cluster + install testbed (Sock Shop, Prometheus, Chaos Mesh, our components)
	bash cluster/bootstrap.sh

down: ## delete the whole cluster
	kind delete cluster --name $(CLUSTER)

deploy: ## re-apply just our components (after code/manifest changes)
	kubectl apply -k deploy/platform/overlays/local

load: ## run a k6 load Job against Sock Shop (REGIME=steady|ramp|spike|soak)
	REGIME=$${REGIME:-ramp} envsubst < experiment/load/k6-job.yaml | kubectl apply -f -

chaos: ## list chaos experiments (apply one: kubectl apply -f experiment/faults/<name>.yaml)
	@ls experiment/faults/*.yaml 2>/dev/null || echo "no fault manifests yet"

selftest: ## run every module's offline self-check (no cluster needed)
	@for m in ingest detect rca predict forecast scaler remediate explain; do \
		echo "== $$m =="; python -m aiops.$$m --selftest || exit 1; done

ps: ## what's running
	kubectl get pods -A | grep -E 'sock-shop|monitoring|chaos-mesh|aiops' || true
