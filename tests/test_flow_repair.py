# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.

from __future__ import annotations

import json
import os
import subprocess
import sys

import urirun
import yaml

import urirun_connector_flow_repair.core as core
from urirun_connector_flow_repair import connector_manifest, repair_loop, run_repair, urirun_bindings

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLSTUB = [sys.executable, os.path.join(HERE, "toolstub.py")]
ROUTE = "flow://host/repair/command/run"


def _registry() -> dict:
    raw = subprocess.run(TOOLSTUB + ["bindings"], capture_output=True, text=True, check=True).stdout
    return urirun.compile_registry(json.loads(raw))


def _cleanup() -> None:
    p = os.path.join(HERE, "_notes.json")
    if os.path.exists(p):
        os.remove(p)


def _stub_planner(goal, allowed, feedback=None):
    """Emulates an LLM: empty key first, fills it once the failure mentions `key`."""
    needs_fix = bool(feedback) and "key" in json.dumps(feedback).lower()
    steps = [{"id": "stamp", "uri": "time://host/clock/query/now"},
             {"id": "save", "uri": "note://host/store/command/put",
              "payload": {"key": "k1" if needs_fix else "", "value": goal}}]
    return yaml.safe_dump({"task": {"title": goal}, "steps": steps})


# --- the loop ---------------------------------------------------------------

def test_repair_loop_recovers_on_second_attempt() -> None:
    _cleanup()
    report = repair_loop("save a note", _registry(), _stub_planner, execute=True, tries=3)
    assert report["succeeded"] is True
    assert report["attempts"] == 2
    assert report["transcript"][0]["ok"] is False
    assert "key is required" in report["transcript"][0]["failed"]["error"]
    assert report["transcript"][1]["ok"] is True
    _cleanup()


def test_validate_rejects_unknown_uri() -> None:
    def bad(goal, allowed, feedback=None):
        return yaml.safe_dump({"steps": [{"id": "s1", "uri": "shell://host/run/command/exec"}]})

    report = repair_loop("x", _registry(), bad, execute=True, tries=2)
    assert report["succeeded"] is False
    assert report["lastError"]["stage"] == "validate"
    assert "shell://host/run/command/exec" in report["lastError"]["unknownUris"]


def test_normalizes_loose_llm_yaml() -> None:
    # a real model often emits `task` as a string and integer `id`s; the loop
    # should coerce those rather than burn a repair attempt on them.
    _cleanup()

    def loose(goal, allowed, feedback=None):
        return ("task: just a title\n"
                "steps:\n- id: 1\n  uri: note://host/store/command/put\n"
                "  payload: {key: k, value: v}\n")

    report = repair_loop("x", _registry(), loose, execute=True, tries=1)
    assert report["succeeded"] is True
    assert report["flow"]["task"] == {"title": "just a title"}
    assert report["flow"]["steps"][0]["id"] == "1"
    _cleanup()


def test_dry_run_plans_without_executing() -> None:
    _cleanup()
    report = repair_loop("save a note", _registry(), _stub_planner, execute=False, tries=1)
    assert report["succeeded"] is True              # note tool never ran, so empty key never failed
    assert not os.path.exists(os.path.join(HERE, "_notes.json"))


# --- the llm-backed planner (delegates to the llm connector) ----------------

def test_llm_planner_calls_llm_connector(monkeypatch) -> None:
    import urirun_connector_llm
    captured = {}

    def fake_complete(prompt, model="", base_url="", provider=""):
        captured["model"] = model
        captured["provider"] = provider
        return {"ok": True, "response": "```yaml\ntask: {title: x}\nsteps: []\n```"}

    monkeypatch.setattr(urirun_connector_llm, "complete", fake_complete)
    plan = core._llm_planner("openrouter/anthropic/claude-3.5-sonnet", "", "")
    out = plan("goal", ["time://host/clock/query/now"], None)
    assert "task:" in out and "```" not in out          # fences stripped
    assert captured["model"] == "openrouter/anthropic/claude-3.5-sonnet"


# --- handler surface --------------------------------------------------------

def test_run_repair_requires_goal_and_registry() -> None:
    assert run_repair("", "reg.json")["ok"] is False
    r = run_repair("do x", "")
    assert r["ok"] is False and "registry" in r["error"]


def test_bindings_are_isolated_handler() -> None:
    b = urirun_bindings()["bindings"]
    assert set(b) == {ROUTE}
    assert b[ROUTE]["adapter"] == "local-function-subprocess"
    assert b[ROUTE]["python"]["export"] == "run_repair"
    json.dumps(urirun_bindings())


def test_compiles_and_route_present() -> None:
    registry = urirun.compile_registry(json.loads(json.dumps(urirun_bindings())))
    assert ROUTE in {r["uri"] for r in urirun.list_routes(registry)}


def test_manifest() -> None:
    m = connector_manifest()
    assert m["id"] == "flow-repair"
    assert set(m["routes"]) == {ROUTE}
    assert m["uriSchemes"] == ["flow"]
