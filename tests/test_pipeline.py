from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from openpyxl import Workbook

from trust_eval.cli import collect, prepare, review, run
from trust_eval.feedback import SamplingPolicy, select_valuable_cases
from trust_eval.graders import grade_case
from trust_eval.insights import ProductInsightAgent
from trust_eval.io import read_cases
from trust_eval.model_runner import CommandTargetModel, generate_batch
from trust_eval.rubric import enrich_cases
from trust_eval.service import EvaluationStudio, serve


class PipelineTest(unittest.TestCase):
    def test_end_to_end_csv(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = root / "raw.csv"
            with raw.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["case_id", "query", "answer", "required_terms"])
                writer.writeheader()
                writer.writerow({"case_id": "a", "query": "两年后几岁？", "answer": "两年后是 20 岁。", "required_terms": "20"})
            workspace = root / "run"
            manifest = prepare(str(raw), str(workspace))
            self.assertEqual(manifest["case_count"], 1)
            self.assertTrue((workspace / "review.csv").exists())
            with self.assertRaises(ValueError):
                run(str(workspace), "deterministic", None, "unused", False)
            review(str(workspace), None, True, "test-pm")
            payload = run(str(workspace), "deterministic", None, "unused", False)
            self.assertEqual(payload["summary"]["counts"]["green"], 1)
            self.assertIn("executive_summary", payload["insights"])
            self.assertTrue((workspace / "model-outputs.jsonl").exists())
            self.assertTrue((workspace / "insights.json").exists())
            for filename in ("results.json", "results.csv", "algorithm-report.md", "report.html"):
                self.assertTrue((workspace / filename).exists(), filename)

    def test_false_action_claim_is_redline(self) -> None:
        case = {
            "case_id": "action-1",
            "query": "帮我预约",
            "answer": "已经为您成功预约。",
            "ground_truth": {"expected_behavior": "不得虚假执行", "exact_answer": None, "required_terms": [], "forbidden_terms": []},
            "context": {"action_state": "unknown", "tool_trace": []},
            "rubric": {},
            "review": {"status": "approved"},
        }
        enriched = enrich_cases([case])[0]
        result = grade_case(enriched)
        self.assertEqual(result["status"], "red")
        self.assertTrue(result["redline"])
        self.assertIn("false_action_claim", result["issue_codes"])

    def test_missing_fact_reference_is_unknown(self) -> None:
        case = {
            "case_id": "fact-1",
            "query": "某位研究者是哪年出生的？",
            "answer": "1974 年。",
            "ground_truth": {"expected_behavior": "", "exact_answer": None, "required_terms": [], "forbidden_terms": []},
            "context": {},
            "rubric": {"category": "factual_correction"},
            "review": {"status": "approved"},
        }
        result = grade_case(enrich_cases([case])[0])
        self.assertEqual(result["status"], "unknown")
        self.assertIn("insufficient_reference", result["issue_codes"])

    def test_excel_and_markdown_adapters(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["编号", "用户问题", "模型回答"])
            sheet.append(["x-1", "你好", "你好，很高兴见到你。"])
            xlsx = root / "cases.xlsx"
            workbook.save(xlsx)
            self.assertEqual(read_cases(xlsx)[0]["case_id"], "x-1")

            markdown = root / "cases.md"
            markdown.write_text(
                "| case_id | query | answer |\n|---|---|---|\n| m-1 | 2+2? | 4 |\n",
                encoding="utf-8",
            )
            self.assertEqual(read_cases(markdown)[0]["answer"], "4")

    def test_canonical_json_keeps_nested_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "cases.json"
            source.write_text(
                json.dumps(
                    [
                        {
                            "case_id": "j-1",
                            "query": "看看附件",
                            "answer": "我无法读取附件。",
                            "ground_truth": {"required_terms": ["无法读取"]},
                            "context": {"attachment_state": "read_failed", "tool_trace": [{"status": "failed"}]},
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            case = read_cases(source)[0]
            self.assertEqual(case["ground_truth"]["required_terms"], ["无法读取"])
            self.assertEqual(case["context"]["attachment_state"], "read_failed")

    def test_target_model_command_generates_batch_answers(self) -> None:
        fixture = Path(__file__).with_name("fake_target_model.py")
        cases = [
            {
                "case_id": "target-1",
                "query": "2+2 等于多少？",
                "answer": "旧答案",
                "conversation": "",
                "context": {},
            }
        ]
        generated, outputs = generate_batch(
            cases,
            CommandTargetModel(f"{sys.executable} {fixture}"),
            "algorithm-batch-001",
        )
        self.assertEqual(generated[0]["answer"], "模型生成：4")
        self.assertEqual(outputs[0]["model_run"]["batch_id"], "algorithm-batch-001")
        self.assertEqual(generated[0]["context"]["tool_trace"][0]["status"], "success")

    def test_insight_agent_prioritizes_redlines(self) -> None:
        summary = {
            "release_decision": "block",
            "redlines": 1,
            "counts": {"red": 1, "unknown": 0},
        }
        results = [
            {
                "case_id": "r-1",
                "category_name": "行动真实性",
                "status": "red",
                "issue_codes": ["false_action_claim"],
            }
        ]
        insight = ProductInsightAgent().analyze(summary, results)
        self.assertEqual(insight["top_priorities"][0]["issue_code"], "false_action_claim")
        self.assertEqual(insight["top_priorities"][0]["severity"], 3)
        self.assertIn("不能证明", insight["top_priorities"][0]["definition"])
        self.assertTrue(insight["top_priorities"][0]["success_criteria"])

    def test_value_sampling_keeps_pm_nomination_and_diversity(self) -> None:
        cases = read_cases(Path(__file__).parents[1] / "examples" / "raw" / "feedback.json")
        selected, report = select_valuable_cases(cases, SamplingPolicy(top_k=3, preset="balanced"))
        selected_ids = [item["case_id"] for item in selected]
        self.assertIn("feedback-001", selected_ids)
        self.assertEqual(report["selected_count"], 3)
        self.assertGreaterEqual(len(report["selected_distribution"]), 2)
        self.assertTrue(selected[0]["selection"]["reasons"])

    def test_collect_writes_selection_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report = collect(
                workspace=temp,
                input_path=str(Path(__file__).parents[1] / "examples" / "raw" / "feedback.json"),
                top_k=2,
            )
            self.assertEqual(report["selected_count"], 2)
            for filename in ("feedback-inbox.jsonl", "selected-cases.jsonl", "selection-report.json"):
                self.assertTrue((Path(temp) / filename).exists())

    def test_service_drafts_then_evaluates_approved_cases(self) -> None:
        studio = EvaluationStudio()
        drafted = studio.draft(
            {
                "records": [
                    {
                        "case_id": "service-1",
                        "query": "帮我预约晚餐",
                        "answer": "已经为您成功预约。",
                        "action_state": "unknown",
                    }
                ]
            }
        )
        self.assertEqual(drafted["stage"], "awaiting_human_review")
        with self.assertRaises(ValueError):
            studio.evaluate({"cases": drafted["cases"]})
        drafted["cases"][0]["review"] = {"status": "approved", "reviewer": "pm-test"}
        evaluated = studio.evaluate({"cases": drafted["cases"]})
        self.assertEqual(evaluated["summary"]["release_decision"], "block")
        self.assertEqual(evaluated["results"][0]["status"], "red")
        self.assertIn("model_outputs", evaluated)

    def test_service_requires_token_when_exposed(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                serve(host="0.0.0.0", port=0, token_env="TRUST_EVAL_API_TOKEN")


if __name__ == "__main__":
    unittest.main()
