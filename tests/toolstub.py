# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.
#
# Minimal self-contained "connector" used only by the flow-repair tests: it gives
# the loop a real action space with one route (`note put`) that fails on bad input
# (empty key), so the repair path is exercised fully offline.

from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.abspath(__file__)
SELF = [sys.executable, HERE]
NOTES_FILE = os.path.join(os.path.dirname(HERE), "_notes.json")


def _route(uri, argv, properties, label, *, required=None):
    schema = {"type": "object", "additionalProperties": False, "properties": properties}
    if required:
        schema["required"] = required
    return {uri: {"adapter": "argv-template", "kind": "command", "argv": argv,
                  "inputSchema": schema, "meta": {"connector": "flow-repair-test", "label": label}, "uri": uri}}


def bindings() -> dict:
    b: dict = {}
    b.update(_route("time://host/clock/query/now", SELF + ["now"], {}, "Current UTC time"))
    b.update(_route("note://host/store/command/put",
                    SELF + ["note-put", "--key", "{key}", "--value", "{value}"],
                    {"key": {"type": "string"}, "value": {"type": "string", "default": ""}},
                    "Store a note under a key", required=["key"]))
    return {"version": "urirun.bindings.v2", "bindings": b}


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    flags = {argv[i][2:]: argv[i + 1] for i in range(1, len(argv) - 1, 2) if argv[i].startswith("--")}
    if cmd == "bindings":
        print(json.dumps(bindings())); return 0
    if cmd == "now":
        print(json.dumps({"ok": True, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})); return 0
    if cmd == "note-put":
        key = flags.get("key", "")
        if not key.strip():
            print(json.dumps({"ok": False, "error": "key is required and must be non-empty"})); return 0
        print(json.dumps({"ok": True, "stored": key})); return 0
    print("usage: toolstub.py {bindings|now|note-put}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
