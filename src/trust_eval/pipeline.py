from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .graders import SemanticJudge, aggregate_results, grade_case
from .insights import InsightAgent, ProductInsightAgent
from .model_runner import ExistingAnswerModel, TargetModel, generate_batch


def dataset_hash(cases: list[dict[str, Any]]) -> str:
    stable = json.dumps(cases, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(stable.encode()).hexdigest()[:16]


def validate_evalset(cases: list[dict[str, Any]], *, allow_draft: bool = False) -> None:
    if not cases:
        raise ValueError("评测集不能为空")
    case_ids = [str(case.get("case_id", "")) for case in cases]
    if any(not case_id for case_id in case_ids):
        raise ValueError("每个 Case 都必须有 case_id")
    duplicates = sorted({case_id for case_id in case_ids if case_ids.count(case_id) > 1})
    if duplicates:
        raise ValueError(f"case_id 重复：{', '.join(duplicates[:5])}")
    drafts = [
        case_id
        for case_id, case in zip(case_ids, cases)
        if case.get("review", {}).get("status") != "approved"
    ]
    if drafts and not allow_draft:
        preview = ", ".join(drafts[:5])
        raise ValueError(f"有 {len(drafts)} 个标准未获 PM 批准（{preview}）")


def execute_evaluation(
    cases: list[dict[str, Any]],
    *,
    target_model: TargetModel | None = None,
    judge: SemanticJudge | None = None,
    insight_agent: InsightAgent | None = None,
    allow_draft: bool = False,
    batch_id: str | None = None,
    target_model_name: str | None = None,
    judge_model: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Execute the reusable evaluation core without depending on files or CLI state."""

    validate_evalset(cases, allow_draft=allow_draft)
    working_cases = deepcopy(cases)
    provider = target_model or ExistingAnswerModel()
    insight = insight_agent or ProductInsightAgent()
    fingerprint = dataset_hash(working_cases)
    generated_cases, model_outputs = generate_batch(working_cases, provider, batch_id)
    results = [grade_case(case, judge) for case in generated_cases]
    summary = aggregate_results(results)
    try:
        insights = insight.analyze(summary, results)
    except Exception as exc:
        insights = ProductInsightAgent().analyze(summary, results)
        insights["agent_error"] = str(exc)
    run_meta = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "judge": judge.name if judge else "deterministic-v1",
        "judge_model": judge_model,
        "target_model": provider.name,
        "target_model_name": target_model_name,
        "batch_id": model_outputs[0]["model_run"]["batch_id"] if model_outputs else batch_id,
        "dataset_sha256": fingerprint,
        "rubric_version": "three-lens-v1",
        "scoring": "user_value/product_trust/business_acceptability each 0-2",
    }
    return (
        {
            "schema_version": "1.0",
            "run": run_meta,
            "summary": summary,
            "insights": insights,
            "results": results,
        },
        model_outputs,
    )

