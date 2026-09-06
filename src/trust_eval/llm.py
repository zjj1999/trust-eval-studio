from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def openai_structured_output(
    *,
    prompt: str,
    schema: dict[str, Any],
    schema_name: str,
    model: str,
    timeout: int = 90,
) -> dict[str, Any]:
    """Call the Responses API and return one strict JSON object."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 未设置")
    body = json.dumps(
        {
            "model": model,
            "input": prompt,
            "text": {"format": {"type": "json_schema", "name": schema_name, "schema": schema, "strict": True}},
        }
    ).encode()
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"OpenAI HTTP {exc.code}: {exc.read().decode(errors='replace')}") from exc
    output_text = payload.get("output_text")
    if not output_text:
        for item in payload.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    output_text = content.get("text")
                    break
    if not output_text:
        raise RuntimeError("OpenAI 未返回 output_text")
    return json.loads(output_text)
