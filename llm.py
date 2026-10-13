#!/usr/bin/env python3
"""Thin wrapper around the Claude API for the issue builder: one prompt in, schema-valid JSON out."""

import json

import anthropic

MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

_client = None
usage_log = []


def client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def ask_json(system, user, schema, effort="medium", max_tokens=48000, label=""):
    """Run one request and return the parsed JSON object that matches `schema`."""
    with client().beta.messages.stream(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        thinking={"type": "adaptive"},
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        betas=[FALLBACK_BETA],
        fallbacks="default",
    ) as stream:
        message = stream.get_final_message()

    usage_log.append({"label": label, "model": message.model,
                      "input": message.usage.input_tokens, "output": message.usage.output_tokens})
    if message.stop_reason == "refusal":
        raise RuntimeError(f"{label}: the model declined this request ({message.stop_details})")
    if message.stop_reason == "max_tokens":
        raise RuntimeError(f"{label}: output hit the {max_tokens} token limit before finishing")
    text = next(block.text for block in message.content if block.type == "text")
    return json.loads(text)


def obj(properties, **extra):
    """Shorthand for a closed JSON-schema object with every property required."""
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False, **extra}


STR = {"type": "string"}


def arr(items):
    return {"type": "array", "items": items}


def enum(*values):
    return {"type": "string", "enum": list(values)}
