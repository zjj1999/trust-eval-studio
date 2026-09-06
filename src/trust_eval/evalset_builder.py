from __future__ import annotations

import json
import shlex
import subprocess
from collections import Counter
from dataclasses import dataclass
from typing import Any, Protocol

from .llm import openai_structured_output
from .rubric import STANDARDS, draft_rubric, infer_category


class EvalSetAgent(Protocol):
    """Completes raw question/answer rows into reviewable evaluation cases."""

    name: str

    def complete(self, case: dict[str, Any], dataset_profile: dict[str, Any]) -> dict[str, Any]: ...


def analyze_dataset(cases: list[dict[str, Any]]) -> dict[str, Any]:
    categories = Counter(infer_category(case) for case in cases)
    names = [STANDARDS[key]["name"] for key, _ in categories.most_common()]
    if len(names) == 1:
        purpose = f"验证模型在{names[0]}场景中的任务完成度、可信度和上线风险"
    else:
        purpose = f"验证模型在{'、'.join(names[:4])}等场景中的任务完成度、可信度和能力边界"
    reference_ready = sum(
        bool(
            case.get("ground_truth", {}).get("exact_answer")
            or case.get("ground_truth", {}).get("required_terms")
            or case.get("ground_truth", {}).get("forbidden_terms")
        )
        for case in cases
    )
    context_ready = sum(
        case.get("context", {}).get("attachment_state") not in {None, "", "unknown"}
        or bool(case.get("context", {}).get("tool_trace"))
        or case.get("context", {}).get("action_state") not in {None, "", "unknown"}
        for case in cases
    )
    return {
        "purpose": purpose,
        "case_count": len(cases),
        "category_distribution": dict(categories),
        "reference_coverage": round(reference_ready / len(cases), 4) if cases else 0,
        "context_coverage": round(context_ready / len(cases), 4) if cases else 0,
        "human_focus": [
            "核验事实类 ground truth，不能把已有模型回答直接当标准答案",
            "确认附件、工具和真实执行状态",
            "确认哪些失败属于不可上线红线",
        ],
    }


@dataclass
class TemplateEvalSetAgent:
    name: str = "evalset-copilot-template-v1"

    def complete(self, case: dict[str, Any], dataset_profile: dict[str, Any]) -> dict[str, Any]:
        rubric = draft_rubric(case)
        truth = dict(case.get("ground_truth", {}))
        if not truth.get("expected_behavior"):
            truth["expected_behavior"] = STANDARDS[rubric["category"]]["user"]
        needs_domain_review = rubric["category"] == "factual_correction" and not (
            truth.get("exact_answer") or truth.get("required_terms")
        )
        return {
            "ground_truth": truth,
            "rubric": rubric,
            "dataset_purpose": dataset_profile["purpose"],
            "completion": {
                "agent": self.name,
                "confidence": "low" if needs_domain_review else "medium",
                "needs_domain_review": needs_domain_review,
                "review_note": "请补充可核验事实标准" if needs_domain_review else "请确认期望行为和红线",
            },
        }


@dataclass
class CommandEvalSetAgent:
    command: str
    timeout: int = 90
    name: str = "evalset-copilot-command"

    def complete(self, case: dict[str, Any], dataset_profile: dict[str, Any]) -> dict[str, Any]:
        process = subprocess.run(
            shlex.split(self.command),
            input=json.dumps(
                {"task": "complete_eval_case", "dataset_profile": dataset_profile, "case": case},
                ensure_ascii=False,
            ),
            text=True,
            capture_output=True,
            timeout=self.timeout,
            check=False,
        )
        if process.returncode:
            raise RuntimeError(f"evalset agent failed ({process.returncode}): {process.stderr.strip()}")
        return json.loads(process.stdout)


@dataclass
class OpenAIEvalSetAgent:
    model: str = "gpt-5.4-mini"
    name: str = "evalset-copilot-openai"

    def complete(self, case: dict[str, Any], dataset_profile: dict[str, Any]) -> dict[str, Any]:
        prompt = f"""你是评测集共创 Agent，帮助产品经理把线上 question/answer 补全为可审核的评测 Case。
已有 answer 只是待评模型回答，不是 ground truth，禁止因为它写得流畅就把它当标准答案。
先理解整批评测集的目标，再定义本题的期望行为、可自动检查点、三个产品评分标准和上线红线。
如果事实无法从输入可靠确定，不猜 exact_answer，needs_domain_review=true。

DATASET PROFILE:
{json.dumps(dataset_profile, ensure_ascii=False)}

RAW CASE:
{json.dumps(case, ensure_ascii=False)}
"""
        return openai_structured_output(
            prompt=prompt,
            schema=_evalset_schema(),
            schema_name="evalset_case",
            model=self.model,
        )


def _evalset_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "dataset_purpose": {"type": "string"},
            "ground_truth": {
                "type": "object",
                "properties": {
                    "expected_behavior": {"type": "string"},
                    "exact_answer": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "required_terms": {"type": "array", "items": {"type": "string"}},
                    "forbidden_terms": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["expected_behavior", "exact_answer", "required_terms", "forbidden_terms"],
                "additionalProperties": False,
            },
            "rubric": {
                "type": "object",
                "properties": {
                    "category": {"enum": list(STANDARDS)},
                    "user_standard": {"type": "string"},
                    "product_standard": {"type": "string"},
                    "business_standard": {"type": "string"},
                    "red_lines": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["category", "user_standard", "product_standard", "business_standard", "red_lines"],
                "additionalProperties": False,
            },
            "completion": {
                "type": "object",
                "properties": {
                    "confidence": {"enum": ["low", "medium", "high"]},
                    "needs_domain_review": {"type": "boolean"},
                    "review_note": {"type": "string"},
                },
                "required": ["confidence", "needs_domain_review", "review_note"],
                "additionalProperties": False,
            },
        },
        "required": ["dataset_purpose", "ground_truth", "rubric", "completion"],
        "additionalProperties": False,
    }


def complete_evalset(cases: list[dict[str, Any]], agent: EvalSetAgent) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    profile = analyze_dataset(cases)
    for case in cases:
        try:
            completed = agent.complete(case, profile)
        except Exception as exc:
            completed = TemplateEvalSetAgent().complete(case, profile)
            completed["completion"]["agent_error"] = str(exc)
            completed["completion"]["needs_domain_review"] = True
        truth = completed.get("ground_truth", {})
        case["ground_truth"] = {
            "expected_behavior": str(truth.get("expected_behavior", "")),
            "exact_answer": truth.get("exact_answer") or None,
            "required_terms": [str(item) for item in truth.get("required_terms", [])],
            "forbidden_terms": [str(item) for item in truth.get("forbidden_terms", [])],
        }
        proposed_rubric = completed.get("rubric", {})
        case["rubric"] = {"category": proposed_rubric.get("category", infer_category(case))}
        rubric = draft_rubric(case)
        rubric.update(proposed_rubric)
        case["rubric"] = rubric
        case["dataset_purpose"] = completed.get("dataset_purpose", profile["purpose"])
        case["completion"] = {"agent": agent.name, **completed.get("completion", {})}
    profile["architect"] = agent.name
    profile["domain_review_count"] = sum(
        bool(case.get("completion", {}).get("needs_domain_review")) for case in cases
    )
    return cases, profile
