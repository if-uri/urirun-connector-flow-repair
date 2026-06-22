# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.

"""Self-correcting URI-flow connector for urirun.

One route turns a natural-language goal into a urirun flow (YAML), runs it under
policy, and — when a step fails — feeds the structured error back to the LLM to
get a corrected flow, then re-runs. The loop:

    action space (allowed URIs)  ->  LLM emits YAML flow  ->  validate URIs
        ->  run each step (query free / command gated)  ->  ok? done
        ->  not ok? feed {step, uri, error} back to the LLM  ->  retry

Route:

* ``flow://host/repair/command/run`` -- plan + execute + repair a flow from NL

The LLM call is delegated to the ``llm`` connector, so model/provider selection
follows its rules: a provider-prefixed model (``openrouter/...``, ``openai/...``)
goes through litellm with the matching ``*_API_KEY``; a bare model (``llama3``)
hits a local Ollama. Completions are an external call, so the route defaults to
dry-run and only executes steps with ``--execute`` / ``mode=execute``.
"""

from __future__ import annotations

import json
from typing import Any, Callable

import urirun

CONNECTOR_ID = "flow-repair"
conn = urirun.connector(CONNECTOR_ID, scheme="flow")

DEFAULT_MODEL = "llama3"
DEFAULT_BASE_URL = "http://localhost:11434"


# --- registry loading ------------------------------------------------------

def _load_registry(registry: str) -> dict:
    """Load a compiled registry (or raw bindings) from a path."""
    from urirun import v2
    return v2.load_registry_arg(registry)


# --- prompt + YAML helpers -------------------------------------------------

def _build_prompt(goal: str, allowed: list[str], feedback: dict | None) -> str:
    lines = [
        "You convert a goal into a urirun flow. Return ONLY a YAML document, no prose, no code fences.",
        "Exact shape (copy it): `task` is a MAPPING and every step `id` is a STRING in quotes:",
        'task:\n  title: "<short title>"\nsteps:\n  - id: "step1"\n    uri: "scheme://host/.../command/op"\n    payload:\n      field: "value"',
        f"Use ONLY these URIs: {json.dumps(allowed)}.",
        f"GOAL: {goal}",
    ]
    if feedback:
        lines.append("The PREVIOUS flow FAILED — fix it and return a corrected YAML flow.")
        lines.append("Failure (structured):\n" + json.dumps(feedback, ensure_ascii=False, indent=2))
    return "\n".join(lines)


def _normalize_flow_dict(raw: object) -> dict:
    """Coerce the loose shapes models tend to emit into the strict Flow schema:
    `task` as a bare string → {title: ...}; integer step `id`s → strings; a single
    step mapping → a one-item list. Real structural errors still surface."""
    d = dict(raw) if isinstance(raw, dict) else {}
    task = d.get("task")
    if isinstance(task, str):
        d["task"] = {"title": task}
    elif task is None:
        d["task"] = {}
    steps = d.get("steps")
    if isinstance(steps, dict):
        steps = [steps]
    norm = []
    for i, s in enumerate(steps or []):
        if not isinstance(s, dict):
            continue
        s = dict(s)
        s["id"] = str(s.get("id", f"s{i + 1}"))
        if "payload" in s and not isinstance(s["payload"], dict):
            s.pop("payload")
        norm.append(s)
    d["steps"] = norm
    return d


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.removeprefix("yaml\n").strip()


def _llm_planner(model: str, base_url: str, provider: str) -> Callable[[str, list[str], dict | None], str]:
    """A planner that asks the `llm` connector for a YAML flow."""
    from urirun_connector_llm import complete

    def plan(goal: str, allowed: list[str], feedback: dict | None = None) -> str:
        res = complete(_build_prompt(goal, allowed, feedback),
                       model=model, base_url=base_url, provider=provider)
        if not res.get("ok"):
            raise RuntimeError(f"llm error: {res.get('error')}")
        return _strip_fences(res.get("response", ""))

    return plan


# --- the repair loop (planner-injectable, so it is trivially testable) ------

def repair_loop(goal: str, registry: dict, planner: Callable[[str, list[str], dict | None], str],
                *, tries: int = 3, execute: bool = False, allow: list[str] | None = None) -> dict:
    """Plan → validate → execute, repairing from the structured error up to `tries`.

    `planner(goal, allowed_uris, feedback) -> yaml_str`. Returns a structured
    transcript: which YAML each attempt produced and why it failed, plus the
    final outcome.
    """
    import yaml
    from urirun_flow import Flow, FlowError

    space = urirun.action_space(registry)
    allowed = sorted({r["uri"] for r in space})
    allowed_set = set(allowed)
    feedback: dict | None = None
    transcript: list[dict] = []

    for attempt in range(1, max(1, int(tries)) + 1):
        yaml_text = planner(goal, allowed, feedback)
        record: dict[str, Any] = {"attempt": attempt, "yaml": yaml_text}

        try:
            flow = Flow(**_normalize_flow_dict(yaml.safe_load(yaml_text)))
        except (FlowError, ValueError, yaml.YAMLError) as exc:
            feedback = {"stage": "parse", "error": str(exc)}
            record.update(ok=False, feedback=feedback); transcript.append(record); continue

        unknown = [s.uri for s in flow.steps if s.uri not in allowed_set]
        if unknown:
            feedback = {"stage": "validate", "unknownUris": unknown, "allowed": allowed}
            record.update(ok=False, feedback=feedback); transcript.append(record); continue

        results: dict[str, Any] = {}
        failed: dict | None = None
        for step in flow.order():
            scheme = step.uri.split("://", 1)[0]
            policy = urirun.policy(allow=list(allow) if allow else [f"{scheme}://*"])
            env = urirun.run(step.uri, registry, step.payload,
                             mode="execute" if execute else "dry-run", policy=policy)
            data = urirun.result_data(env)
            data = data if isinstance(data, dict) else {"value": data}
            ok = bool(env.get("ok")) and data.get("ok", True)
            results[step.id] = data
            if not ok:
                failed = {"stage": "execute", "step": step.id, "uri": step.uri,
                          "error": data.get("error") or env.get("error") or "step returned ok=false",
                          "data": data}
                break

        record.update(ok=failed is None, results=results, failed=failed)
        transcript.append(record)
        if failed is None:
            return {"succeeded": True, "attempts": attempt, "flow": flow.to_dict(),
                    "transcript": transcript, "results": results}
        feedback = failed

    return {"succeeded": False, "attempts": len(transcript), "transcript": transcript, "lastError": feedback}


# --- route handler ---------------------------------------------------------

@conn.handler("repair/command/run", isolated=True, meta={"label": "Plan + execute + repair a flow from NL"})
def run_repair(goal: str = "", registry: str = "", model: str = DEFAULT_MODEL,
               base_url: str = DEFAULT_BASE_URL, provider: str = "", tries: int = 3,
               execute: bool = False, allow: list[str] | None = None) -> dict[str, Any]:
    """Generate a YAML flow for `goal` against the `registry` action space, run it,
    and repair from any failure by feeding the error back to the LLM."""
    if not goal:
        return urirun.fail("goal is required")
    if not registry:
        return urirun.fail("registry is required (path to a compiled registry / bindings)")
    try:
        reg = _load_registry(registry)
    except (OSError, ValueError) as exc:
        return urirun.fail(f"cannot load registry: {exc}")
    planner = _llm_planner(model, base_url, provider)
    try:
        result = repair_loop(goal, reg, planner, tries=int(tries), execute=bool(execute), allow=allow)
    except RuntimeError as exc:
        return urirun.fail(str(exc))
    return urirun.ok(**result)


# --- authoring surface -----------------------------------------------------

def urirun_bindings() -> dict[str, Any]:
    """Serializable v2 bindings for this connector (entry point: urirun.bindings)."""
    return conn.bindings()


def connector_manifest() -> dict[str, Any]:
    return conn.manifest(urirun.load_manifest(__package__))


def main(argv: list[str] | None = None) -> int:
    return conn.cli(argv, manifest_prose=urirun.load_manifest(__package__))


if __name__ == "__main__":
    raise SystemExit(main())
