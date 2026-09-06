from __future__ import annotations

import json
import os
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .evalset_builder import OpenAIEvalSetAgent, TemplateEvalSetAgent, complete_evalset
from .feedback import SamplingPolicy, select_valuable_cases
from .graders import OpenAIJudge
from .insights import OpenAIInsightAgent, ProductInsightAgent
from .io import normalize_records
from .model_runner import ExistingAnswerModel, HttpTargetModel
from .pipeline import execute_evaluation
from .rubric import enrich_cases


MAX_CASES = 2000
MAX_BODY_BYTES = 10 * 1024 * 1024


def _items(payload: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            records = [item for item in value if isinstance(item, dict)]
            if len(records) > MAX_CASES:
                raise ValueError(f"单次最多处理 {MAX_CASES} 个 Case")
            return records
    raise ValueError(f"请求必须包含 {'/'.join(keys)} 数组")


@dataclass
class EvaluationStudio:
    """Programmatic facade used by the HTTP API and internal PM tools."""

    def capabilities(self) -> dict[str, Any]:
        return {
            "service": "trust-eval-studio",
            "version": "1.0",
            "workflow": ["select", "draft", "human_review", "evaluate", "insight"],
            "endpoints": {
                "select": "POST /v1/cases/select",
                "draft": "POST /v1/evalsets/draft",
                "evaluate": "POST /v1/evaluations/run",
                "pipeline": "POST /v1/pipeline/run",
                "insight": "POST /v1/insights/generate",
            },
            "target_types": ["existing", "http"],
            "judge_types": ["deterministic", "openai"],
            "insight_types": ["template", "openai"],
            "guardrails": [
                "正式评测默认要求 PM approved",
                "HTTP 服务不接受任意 command 执行",
                f"单次最多 {MAX_CASES} 个 Case",
            ],
        }

    def select(self, payload: dict[str, Any]) -> dict[str, Any]:
        records = _items(payload, "records", "cases", "items")
        cases = normalize_records(records, "service:business-feedback")
        config = payload.get("policy") if isinstance(payload.get("policy"), dict) else {}
        policy = SamplingPolicy(
            top_k=int(config.get("top_k", min(50, len(cases)))),
            preset=str(config.get("preset", "balanced")),
            max_per_category=int(config["max_per_category"]) if config.get("max_per_category") else None,
            min_score=float(config.get("min_score", 0)),
            deduplicate=bool(config.get("deduplicate", True)),
        )
        selected, report = select_valuable_cases(cases, policy)
        return {"selected_cases": selected, "selection_report": report}

    def draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        records = _items(payload, "records", "cases", "selected_cases")
        cases = normalize_records(records, "service:evalset-draft")
        architect = payload.get("architect") if isinstance(payload.get("architect"), dict) else {}
        architect_type = str(architect.get("type", "template"))
        if architect_type == "openai":
            agent = OpenAIEvalSetAgent(model=str(architect.get("model", "gpt-5.4-mini")))
        elif architect_type == "template":
            agent = TemplateEvalSetAgent()
        else:
            raise ValueError("HTTP 服务仅支持 template/openai architect；内部命令请使用 CLI")
        drafted, profile = complete_evalset(cases, agent)
        return {
            "stage": "awaiting_human_review",
            "dataset_profile": profile,
            "cases": drafted,
            "next_action": "PM 确认 ground truth、三维评分标准与红线，并将 review.status 设为 approved",
        }

    def evaluate(self, payload: dict[str, Any]) -> dict[str, Any]:
        cases = enrich_cases(_items(payload, "cases", "evalset"))
        target_config = payload.get("target") if isinstance(payload.get("target"), dict) else {}
        target_type = str(target_config.get("type", "existing"))
        if target_type == "http":
            endpoint = str(target_config.get("endpoint", ""))
            if not endpoint:
                raise ValueError("target.type=http 时必须提供 target.endpoint")
            target = HttpTargetModel(
                url=endpoint,
                model=str(target_config.get("model", "")),
                protocol=str(target_config.get("protocol", "simple")),
                api_key_env=str(target_config.get("api_key_env", "MODEL_API_KEY")),
                timeout=int(target_config.get("timeout", 120)),
            )
        elif target_type == "existing":
            target = ExistingAnswerModel()
        else:
            raise ValueError("HTTP 服务仅支持 existing/http target；内部命令请使用 CLI")

        judge_config = payload.get("judge") if isinstance(payload.get("judge"), dict) else {}
        judge_type = str(judge_config.get("type", "deterministic"))
        if judge_type == "openai":
            judge_model = str(judge_config.get("model", "gpt-5.4-mini"))
            judge = OpenAIJudge(model=judge_model, timeout=int(judge_config.get("timeout", 90)))
        elif judge_type == "deterministic":
            judge_model = None
            judge = None
        else:
            raise ValueError("HTTP 服务仅支持 deterministic/openai judge；内部命令请使用 CLI")

        insight_config = payload.get("insight") if isinstance(payload.get("insight"), dict) else {}
        insight_type = str(insight_config.get("type", "template"))
        if insight_type == "openai":
            insight = OpenAIInsightAgent(model=str(insight_config.get("model", "gpt-5.4-mini")))
        elif insight_type == "template":
            insight = ProductInsightAgent()
        else:
            raise ValueError("HTTP 服务仅支持 template/openai insight；内部命令请使用 CLI")

        result, model_outputs = execute_evaluation(
            cases,
            target_model=target,
            judge=judge,
            insight_agent=insight,
            allow_draft=bool(payload.get("allow_draft", False)),
            batch_id=payload.get("batch_id"),
            target_model_name=str(target_config.get("model", "")) or None,
            judge_model=judge_model,
        )
        return {**result, "model_outputs": model_outputs}

    def insight(self, payload: dict[str, Any]) -> dict[str, Any]:
        summary = payload.get("summary")
        results = payload.get("results")
        if not isinstance(summary, dict) or not isinstance(results, list):
            raise ValueError("请求必须包含 summary 对象和 results 数组")
        config = payload.get("insight") if isinstance(payload.get("insight"), dict) else {}
        if config.get("type") == "openai":
            agent = OpenAIInsightAgent(model=str(config.get("model", "gpt-5.4-mini")))
        else:
            agent = ProductInsightAgent()
        return {"insights": agent.analyze(summary, results)}


class _Handler(BaseHTTPRequestHandler):
    studio = EvaluationStudio()
    token: str | None = None
    max_body_bytes = MAX_BODY_BYTES
    cors_origin: str | None = None

    def _headers(self, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if self.cors_origin:
            self.send_header("Access-Control-Allow-Origin", self.cors_origin)
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        self._headers(status)
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode())

    def _authorized(self) -> bool:
        if not self.token:
            return True
        return self.headers.get("Authorization", "") == f"Bearer {self.token}"

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1:
            return {}
        if length > self.max_body_bytes:
            raise ValueError(f"请求体超过 {self.max_body_bytes // 1024 // 1024} MB 限制")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise ValueError("JSON 请求体必须是对象")
        return payload

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._headers(HTTPStatus.NO_CONTENT)

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            self._json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        if self.path in {"/", "/health", "/v1/capabilities"}:
            payload = {"status": "ok"} if self.path == "/health" else self.studio.capabilities()
            self._json(payload)
            return
        self._json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        routes = {
            "/v1/cases/select": self.studio.select,
            "/v1/evalsets/draft": self.studio.draft,
            "/v1/evaluations/run": self.studio.evaluate,
            "/v1/pipeline/run": self.studio.evaluate,
            "/v1/insights/generate": self.studio.insight,
        }
        action = routes.get(self.path)
        if not action:
            self._json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            self._json(action(self._body()))
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self._json({"error": "invalid_request", "message": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._json({"error": "pipeline_failed", "message": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, format: str, *args: Any) -> None:
        # Avoid printing request bodies or credentials. Keep only the standard request line.
        super().log_message(format, *args)


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    token_env: str = "TRUST_EVAL_API_TOKEN",
    cors_origin: str | None = None,
    max_body_bytes: int = MAX_BODY_BYTES,
) -> None:
    token = os.environ.get(token_env)
    if host not in {"127.0.0.1", "localhost", "::1"} and not token:
        raise ValueError(f"监听非本机地址时必须设置 {token_env}")
    handler = type(
        "TrustEvalHandler",
        (_Handler,),
        {"token": token, "cors_origin": cors_origin, "max_body_bytes": max_body_bytes},
    )
    server = ThreadingHTTPServer((host, port), handler)
    print(f"TrustEval Studio API: http://{host}:{port}")
    print("Capabilities: GET /v1/capabilities")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

