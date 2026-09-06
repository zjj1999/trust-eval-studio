from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .evalset_builder import (
    CommandEvalSetAgent,
    OpenAIEvalSetAgent,
    TemplateEvalSetAgent,
    complete_evalset,
)
from .graders import CommandJudge, OpenAIJudge, aggregate_results, grade_case
from .insights import CommandInsightAgent, OpenAIInsightAgent, ProductInsightAgent
from .io import read_cases, read_jsonl, write_json, write_jsonl
from .model_runner import CommandTargetModel, ExistingAnswerModel, HttpTargetModel, generate_batch
from .reporting import write_reports
from .rubric import apply_review, approve_all, write_review_csv


def _workspace(value: str) -> Path:
    target = Path(value).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    return target


def _dataset_hash(cases: list[dict[str, Any]]) -> str:
    stable = json.dumps(cases, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(stable.encode()).hexdigest()[:16]


def _evalset_agent(name: str, command: str | None, model: str):
    if name == "openai":
        return OpenAIEvalSetAgent(model=model)
    if name == "command":
        if not command:
            raise ValueError("--architect command 需要 --architect-command")
        return CommandEvalSetAgent(command)
    return TemplateEvalSetAgent()


def prepare(
    input_path: str,
    workspace: str,
    architect_name: str = "template",
    architect_command: str | None = None,
    architect_model: str = "gpt-5.4-mini",
) -> dict[str, Any]:
    target = _workspace(workspace)
    agent = _evalset_agent(architect_name, architect_command, architect_model)
    cases, dataset_profile = complete_evalset(read_cases(input_path), agent)
    write_jsonl(target / "cases.jsonl", cases)
    write_review_csv(target / "review.csv", cases)
    write_json(target / "dataset-profile.json", dataset_profile)
    manifest = {
        "schema_version": "1.0",
        "source": str(Path(input_path).expanduser().resolve()),
        "case_count": len(cases),
        "dataset_sha256": _dataset_hash(cases),
        "dataset_profile": dataset_profile,
        "architect": agent.name,
        "review_status": "draft",
    }
    write_json(target / "manifest.json", manifest)
    return manifest


def review(workspace: str, review_file: str | None, approve_demo: bool, reviewer: str) -> dict[str, Any]:
    target = _workspace(workspace)
    cases_path = target / "cases.jsonl"
    if not cases_path.exists():
        raise FileNotFoundError(f"缺少 {cases_path}，请先运行 prepare")
    cases = read_jsonl(cases_path)
    if approve_demo:
        cases = approve_all(cases, reviewer)
    else:
        source = Path(review_file).expanduser().resolve() if review_file else target / "review.csv"
        cases = apply_review(cases, source)
    write_jsonl(cases_path, cases)
    write_review_csv(target / "review.csv", cases)
    approved = sum(case["review"]["status"] == "approved" for case in cases)
    manifest_path = target / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest.update(
        {
            "case_count": len(cases),
            "approved_count": approved,
            "review_status": "approved" if approved == len(cases) else "partial",
            "dataset_sha256": _dataset_hash(cases),
        }
    )
    write_json(manifest_path, manifest)
    return manifest


def run(
    workspace: str,
    judge_name: str,
    judge_command: str | None,
    model: str,
    allow_draft: bool,
    target_name: str = "existing",
    target_endpoint: str | None = None,
    target_command: str | None = None,
    target_protocol: str = "simple",
    target_model: str = "",
    target_api_key_env: str = "MODEL_API_KEY",
    batch_id: str | None = None,
    insight_name: str = "template",
    insight_command: str | None = None,
    insight_model: str = "gpt-5.4-mini",
) -> dict[str, Any]:
    target = _workspace(workspace)
    cases = read_jsonl(target / "cases.jsonl")
    drafts = [case["case_id"] for case in cases if case.get("review", {}).get("status") != "approved"]
    if drafts and not allow_draft:
        preview = ", ".join(drafts[:5])
        raise ValueError(f"有 {len(drafts)} 个标准未获 PM 批准（{preview}）。请先 review，或仅在调试时使用 --allow-draft")
    judge = None
    if judge_name == "openai":
        judge = OpenAIJudge(model=model)
    elif judge_name == "command":
        if not judge_command:
            raise ValueError("--judge command 需要 --judge-command")
        judge = CommandJudge(judge_command)
    if target_name == "http":
        if not target_endpoint:
            raise ValueError("--target http 需要 --target-endpoint")
        target_provider = HttpTargetModel(
            url=target_endpoint,
            model=target_model,
            protocol=target_protocol,
            api_key_env=target_api_key_env,
        )
    elif target_name == "command":
        if not target_command:
            raise ValueError("--target command 需要 --target-command")
        target_provider = CommandTargetModel(target_command)
    else:
        target_provider = ExistingAnswerModel()
    dataset_sha256 = _dataset_hash(cases)
    cases, model_outputs = generate_batch(cases, target_provider, batch_id)
    write_jsonl(target / "model-outputs.jsonl", model_outputs)
    results = [grade_case(case, judge) for case in cases]
    summary = aggregate_results(results)
    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    run_meta = {
        "generated_at": generated_at,
        "judge": judge.name if judge else "deterministic-v1",
        "model": model if judge_name == "openai" else None,
        "target_model": target_provider.name,
        "target_model_name": target_model or None,
        "batch_id": model_outputs[0]["model_run"]["batch_id"] if model_outputs else batch_id,
        "dataset_sha256": dataset_sha256,
        "rubric_version": "three-lens-v1",
        "scoring": "user_value/product_trust/business_acceptability each 0-2",
    }
    if insight_name == "openai":
        insight_agent = OpenAIInsightAgent(model=insight_model)
    elif insight_name == "command":
        if not insight_command:
            raise ValueError("--insight-agent command 需要 --insight-command")
        insight_agent = CommandInsightAgent(insight_command)
    else:
        insight_agent = ProductInsightAgent()
    try:
        insights = insight_agent.analyze(summary, results)
    except Exception as exc:
        insights = ProductInsightAgent().analyze(summary, results)
        insights["agent_error"] = str(exc)
    payload = {
        "schema_version": "1.0",
        "run": run_meta,
        "summary": summary,
        "insights": insights,
        "results": results,
    }
    write_json(target / "results.json", payload)
    write_json(target / "insights.json", insights)
    write_reports(target, summary, results, run_meta, insights)
    return payload


def regenerate_report(
    workspace: str,
    insight_name: str = "template",
    insight_command: str | None = None,
    insight_model: str = "gpt-5.4-mini",
) -> dict[str, Any]:
    target = _workspace(workspace)
    payload = json.loads((target / "results.json").read_text(encoding="utf-8"))
    if insight_name == "openai":
        agent = OpenAIInsightAgent(model=insight_model)
    elif insight_name == "command":
        if not insight_command:
            raise ValueError("--insight-agent command 需要 --insight-command")
        agent = CommandInsightAgent(insight_command)
    else:
        agent = ProductInsightAgent()
    insights = agent.analyze(payload["summary"], payload["results"])
    payload["insights"] = insights
    write_json(target / "results.json", payload)
    write_json(target / "insights.json", insights)
    write_reports(target, payload["summary"], payload["results"], payload["run"], insights)
    return payload


def demo(workspace: str, project_root: Path) -> dict[str, Any]:
    raw = project_root / "examples" / "raw" / "demo.csv"
    prepare(str(raw), workspace)
    review(workspace, None, True, "demo-pm")
    return run(workspace, "deterministic", None, "gpt-5.4-mini", False)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trust-eval", description="可信度评测流水线：导入、共创标准、混合评分与报告")
    sub = parser.add_subparsers(dest="command", required=True)
    for command, help_text in (
        ("build", "评测集共创：标准化数据并由 Agent 补齐 ground truth 与 rubric"),
        ("prepare", "兼容命令：等同 build"),
    ):
        build_parser = sub.add_parser(command, help=help_text)
        build_parser.add_argument("--input", required=True)
        build_parser.add_argument("--workspace", required=True)
        build_parser.add_argument("--architect", choices=["template", "openai", "command"], default="template")
        build_parser.add_argument("--architect-command")
        build_parser.add_argument("--architect-model", default="gpt-5.4-mini")

    review_parser = sub.add_parser("review", help="应用 PM 审核后的 review.csv")
    review_parser.add_argument("--workspace", required=True)
    review_parser.add_argument("--review-file")
    review_parser.add_argument("--approve-demo", action="store_true", help="仅用于演示/测试，批量批准全部标准")
    review_parser.add_argument("--reviewer", default="pm")

    for command, help_text in (
        ("evaluate", "模型自动验收：调用待测模型、评分、计算指标并生成洞察"),
        ("run", "兼容命令：等同 evaluate"),
    ):
        run_parser = sub.add_parser(command, help=help_text)
        run_parser.add_argument("--workspace", required=True)
        run_parser.add_argument("--target", choices=["existing", "http", "command"], default="existing")
        run_parser.add_argument("--target-endpoint")
        run_parser.add_argument("--target-command")
        run_parser.add_argument("--target-protocol", choices=["simple", "openai_chat"], default="simple")
        run_parser.add_argument("--target-model", default="")
        run_parser.add_argument("--target-api-key-env", default="MODEL_API_KEY")
        run_parser.add_argument("--batch-id")
        run_parser.add_argument("--judge", choices=["deterministic", "openai", "command"], default="deterministic")
        run_parser.add_argument("--judge-command")
        run_parser.add_argument("--model", default="gpt-5.4-mini")
        run_parser.add_argument("--insight-agent", choices=["template", "openai", "command"], default="template")
        run_parser.add_argument("--insight-command")
        run_parser.add_argument("--insight-model", default="gpt-5.4-mini")
        run_parser.add_argument("--allow-draft", action="store_true")

    report_parser = sub.add_parser("report", help="洞察交付：不重跑模型，基于已有结果重新生成报告")
    report_parser.add_argument("--workspace", required=True)
    report_parser.add_argument("--insight-agent", choices=["template", "openai", "command"], default="template")
    report_parser.add_argument("--insight-command")
    report_parser.add_argument("--insight-model", default="gpt-5.4-mini")

    demo_parser = sub.add_parser("demo", help="运行内置的非敏感演示集")
    demo_parser.add_argument("--workspace", default="examples/workspace")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        if args.command in {"prepare", "build"}:
            payload = prepare(
                args.input,
                args.workspace,
                args.architect,
                args.architect_command,
                args.architect_model,
            )
        elif args.command == "review":
            payload = review(args.workspace, args.review_file, args.approve_demo, args.reviewer)
        elif args.command in {"run", "evaluate"}:
            payload = run(
                args.workspace,
                args.judge,
                args.judge_command,
                args.model,
                args.allow_draft,
                args.target,
                args.target_endpoint,
                args.target_command,
                args.target_protocol,
                args.target_model,
                args.target_api_key_env,
                args.batch_id,
                args.insight_agent,
                args.insight_command,
                args.insight_model,
            )
        elif args.command == "report":
            payload = regenerate_report(
                args.workspace,
                args.insight_agent,
                args.insight_command,
                args.insight_model,
            )
        else:
            project_root = Path(__file__).resolve().parents[2]
            payload = demo(args.workspace, project_root)
        summary = payload.get("summary", payload)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"trust-eval: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
