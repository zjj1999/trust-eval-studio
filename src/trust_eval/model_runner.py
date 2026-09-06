from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol


class TargetModel(Protocol):
    name: str

    def generate(self, case: dict[str, Any]) -> dict[str, Any]: ...


def _messages(case: dict[str, Any]) -> list[dict[str, Any]]:
    conversation = case.get("conversation")
    if isinstance(conversation, list) and conversation:
        messages = [item for item in conversation if isinstance(item, dict)]
        if messages and messages[-1].get("content") == case.get("query"):
            return messages
        return [*messages, {"role": "user", "content": case.get("query", "")}]
    return [{"role": "user", "content": case.get("query", "")}]


@dataclass
class ExistingAnswerModel:
    name: str = "existing-answer"

    def generate(self, case: dict[str, Any]) -> dict[str, Any]:
        return {"answer": case.get("answer", ""), "trace": [], "raw": None, "latency_ms": 0}


@dataclass
class CommandTargetModel:
    command: str
    timeout: int = 120
    name: str = "command-model-endpoint"

    def generate(self, case: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        process = subprocess.run(
            shlex.split(self.command),
            input=json.dumps(
                {"case_id": case["case_id"], "query": case["query"], "conversation": case.get("conversation")},
                ensure_ascii=False,
            ),
            text=True,
            capture_output=True,
            timeout=self.timeout,
            check=False,
        )
        if process.returncode:
            raise RuntimeError(f"target model failed ({process.returncode}): {process.stderr.strip()}")
        try:
            payload = json.loads(process.stdout)
            if not isinstance(payload, dict):
                raise ValueError("JSON result must be an object")
            answer = payload.get("answer") or payload.get("output_text") or ""
            trace = payload.get("trace") or payload.get("tool_trace") or []
        except (json.JSONDecodeError, ValueError):
            payload = None
            answer = process.stdout.strip()
            trace = []
        return {
            "answer": str(answer),
            "trace": trace,
            "raw": payload,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }


@dataclass
class HttpTargetModel:
    url: str
    model: str = ""
    protocol: str = "simple"
    api_key_env: str = "MODEL_API_KEY"
    timeout: int = 120
    name: str = "http-model-endpoint"

    def generate(self, case: dict[str, Any]) -> dict[str, Any]:
        messages = _messages(case)
        if self.protocol == "openai_chat":
            request_body: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "metadata": {"case_id": case["case_id"]},
            }
        else:
            request_body = {
                "case_id": case["case_id"],
                "query": case["query"],
                "conversation": case.get("conversation"),
                "model": self.model or None,
            }
        headers = {"Content-Type": "application/json"}
        api_key = os.environ.get(self.api_key_env)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request = urllib.request.Request(
            self.url,
            data=json.dumps(request_body, ensure_ascii=False).encode(),
            headers=headers,
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"model endpoint HTTP {exc.code}: {exc.read().decode(errors='replace')}") from exc
        if self.protocol == "openai_chat":
            answer = payload.get("output_text")
            if not answer:
                choices = payload.get("choices") or []
                answer = choices[0].get("message", {}).get("content", "") if choices else ""
        else:
            answer = payload.get("answer") or payload.get("output_text") or payload.get("response") or ""
        return {
            "answer": str(answer),
            "trace": payload.get("trace") or payload.get("tool_trace") or [],
            "raw": payload,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }


def generate_batch(
    cases: list[dict[str, Any]],
    model: TargetModel,
    batch_id: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    resolved_batch = batch_id or datetime.now(timezone.utc).strftime("batch-%Y%m%d-%H%M%S")
    outputs: list[dict[str, Any]] = []
    for case in cases:
        original_answer = case.get("answer", "")
        try:
            generated = model.generate(case)
            case["answer"] = generated.get("answer", "")
            if generated.get("trace"):
                case.setdefault("context", {})["tool_trace"] = generated["trace"]
            error = None
        except Exception as exc:
            generated = {"answer": "", "trace": [], "raw": None, "latency_ms": None}
            case["answer"] = ""
            error = str(exc)
        model_run = {
            "batch_id": resolved_batch,
            "target_model": model.name,
            "latency_ms": generated.get("latency_ms"),
            "error": error,
            "original_answer_preserved": bool(original_answer) and model.name != "existing-answer",
        }
        case.setdefault("context", {})["model_run"] = model_run
        outputs.append(
            {
                "case_id": case["case_id"],
                "query": case["query"],
                "answer": case["answer"],
                "trace": generated.get("trace", []),
                "model_run": model_run,
            }
        )
    return cases, outputs
