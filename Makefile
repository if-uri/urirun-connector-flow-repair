.PHONY: help manifest bindings test test-local smoke
# Sibling checkouts so dev runs without installing the git deps.
SIBLINGS := $(abspath ..)/urirun/adapters/python:$(abspath ..)/urirun-flow/src:$(abspath ..)/urirun-connector-llm
PP := $(CURDIR):$(SIBLINGS)

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-12s %s\n",$$1,$$2}'
manifest: ## Print the connector manifest
	urirun-connector-flow-repair manifest
bindings: ## Print urirun bindings
	urirun-connector-flow-repair bindings
test: ## Install editable + pytest
	pip install -e . && python3 -m pytest -q
test-local: ## Run tests against sibling checkouts (no install)
	PYTHONPATH="$(PP)" python3 -m pytest -q
smoke: ## bindings -> urirun connectors smoke (dry-run, no LLM/backend needed)
	PYTHONPATH="$(PP)" urirun-connector-flow-repair bindings | urirun connectors smoke - \
	  --run 'flow://host/repair/command/run' --payload '{"goal":"x","registry":"reg.json"}' \
	  --allow 'flow://*' --name flow-repair
