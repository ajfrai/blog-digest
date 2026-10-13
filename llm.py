#!/usr/bin/env python3
"""Thin wrapper around the Claude Code CLI (subscription auth) for the issue builder: one prompt in, schema-valid JSON out."""

import json
import os
import subprocess

MODEL = "claude-opus-5-5"
TIMEOUT = 1500

usage_log = []


def ask_json(system, user, schema, effort="medium", max_tokens=None, label=""):
    """Run one request through the `claude` CLI and return the JSON object that matches `schema`.

    This bills the logged-in claude.ai subscription, not the API: ANTHROPIC_API_KEY is removed from the
    child's environment so the CLI falls back to the OAuth login. `max_tokens` is accepted for
    compatibility and ignored (the CLI manages output length).
    """
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    cmd = ["claude", "-p", "--output-format", "json", "--json-schema", json.dumps(schema),
           "--tools", "", "--no-session-persistence", "--system-prompt", system,
           "--setting-sources", "", "--disable-slash-commands", "--strict-mcp-config",
           "--model", MODEL, "--effort", effort]
    proc = subprocess.run(cmd, input=user, capture_output=True, text=True, env=env, timeout=TIMEOUT, cwd="/tmp")
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"{label}: claude CLI failed (exit {proc.returncode}): {(proc.stderr or proc.stdout)[-800:]}")
    if out.get("is_error") or "structured_output" not in out:
        raise RuntimeError(f"{label}: claude CLI error: {str(out.get('result') or out)[:800]}")
    u = out.get("usage", {})
    usage_log.append({"label": label, "model": MODEL, "input": u.get("input_tokens", 0),
                      "output": u.get("output_tokens", 0)})
    return out["structured_output"]


def obj(properties, **extra):
    """Shorthand for a closed JSON-schema object with every property required."""
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False, **extra}


STR = {"type": "string"}


def arr(items):
    return {"type": "array", "items": items}


def enum(*values):
    return {"type": "string", "enum": list(values)}
