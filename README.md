# urirun-connector-flow-repair

Self-correcting URI-flow connector for [ifURI](https://ifuri.com) / urirun.
Turn a natural-language goal into a **urirun flow (YAML)**, run it under policy,
and **repair from a failing step by feeding the structured error back to the
LLM** for a corrected flow — then re-run.

| URI | Operation |
| --- | --- |
| `flow://host/repair/command/run` | plan a YAML flow from NL, execute, and self-repair |

```
action space (allowed URIs)
     │
     ▼
LLM emits a urirun flow as YAML  ──►  validate every step.uri ∈ action space
     ▼
run each step (query free / command gated)   ── dry-run | execute
     ▼
ok? ── yes ─► done
 │ no
 ▼
feedback {step, uri, error}  ──►  LLM patches the flow  ──►  retry (≤ tries)
```

## Payload

| field | default | meaning |
| --- | --- | --- |
| `goal` | — (required) | the natural-language intent |
| `registry` | — (required) | path to a compiled registry / bindings (the action space) |
| `model` | `llama3` | LLM model id (provider-prefixed ⇒ litellm; bare ⇒ Ollama) |
| `base_url` | `http://localhost:11434` | Ollama backend (ignored for litellm models) |
| `provider` | `""` | force `litellm` / `ollama` |
| `tries` | `3` | max attempts (1 plan + repairs) |
| `execute` | `false` | actually run steps; default is a dry-run plan |
| `allow` | per-step `scheme://*` | policy globs for command routes |

The completion is an external call, so the route is **dry-run by default**; pass
`--execute` (CLI) / `mode=execute` (runtime) to run the steps.

## Use

```bash
# via the runtime, against a registry you compiled with `urirun compile`
urirun run 'flow://host/repair/command/run' \
  --payload '{"goal":"zapisz notatkę o uruchomieniu","registry":"reg.json","execute":true}' \
  --allow 'flow://*' --execute
```

Model/provider selection follows the [`llm`](https://github.com/if-uri/urirun-connector-llm)
connector: `model="openrouter/anthropic/claude-3.5-sonnet"` + `OPENROUTER_API_KEY`
goes through litellm; `model="llama3"` hits a local Ollama.

## Why it's safe

- **Action-space validation** — a step whose URI is not in the registry is
  rejected before execution; the model cannot invent a route.
- **Policy gate** — `command` routes run only when `allow` permits; `query`
  routes are read-only. In a mesh the node's own `--allow` is still the hard
  boundary on top of this.
- **Dry-run first** — without `execute` you get the planned YAML and nothing runs.

## Library / testing

`repair_loop(goal, registry, planner, *, tries, execute, allow)` is
planner-injectable, so the loop is testable offline without an LLM:

```python
from urirun_connector_flow_repair import repair_loop
report = repair_loop("save a note", registry, my_planner, execute=True)
# report = {succeeded, attempts, flow, transcript, results | lastError}
```

## Develop

```bash
make test-local   # run tests against sibling checkouts (no install)
make test         # pip install -e . && pytest
```
