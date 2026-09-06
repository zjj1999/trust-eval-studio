# TrustEval contracts

Read this reference when exposing the HTTP service or connecting an internal PM tool.

## Start the local service

```bash
PYTHONPATH=src python3 -m trust_eval serve --port 8787
```

Default binding is `127.0.0.1`. To bind another interface, first set `TRUST_EVAL_API_TOKEN`; clients then send `Authorization: Bearer <token>`.

## Endpoints

### Select high-value feedback

`POST /v1/cases/select`

```json
{
  "records": [{"case_id": "c-1", "query": "...", "answer": "...", "negative_feedback": true}],
  "policy": {"preset": "balanced", "top_k": 50, "deduplicate": true}
}
```

Presets: `balanced`, `risk-first`, `representative`. Output contains `selected_cases` and a transparent `selection_report`.

### Draft an eval set

`POST /v1/evalsets/draft`

```json
{
  "records": [{"case_id": "c-1", "query": "...", "answer": "..."}],
  "architect": {"type": "template"}
}
```

Use `architect.type=openai` with a configured `OPENAI_API_KEY` for semantic drafting. Output remains `awaiting_human_review`.

### Run an approved evaluation

`POST /v1/pipeline/run` or `POST /v1/evaluations/run`

```json
{
  "cases": [{"case_id": "c-1", "query": "...", "answer": "...", "rubric": {}, "review": {"status": "approved"}}],
  "target": {"type": "existing"},
  "judge": {"type": "deterministic"},
  "insight": {"type": "template"},
  "batch_id": "iteration-042"
}
```

For an algorithm Endpoint, use `target.type=http` and provide `endpoint`, `protocol`, `model`, and `api_key_env`. The service never accepts arbitrary shell commands.

### Regenerate product insights

`POST /v1/insights/generate` accepts a `summary` object and a `results` array.

## Artifact contract

- `feedback-inbox.jsonl`: normalized feedback received from the source.
- `selected-cases.jsonl`: transparent high-value sample for co-creation.
- `selection-report.json`: scores, reasons, deduplication, and scene distribution.
- `cases.jsonl`: executable eval set with ground truth, rubric, and review state.
- `review.csv`: PM/expert review surface.
- `model-outputs.jsonl`: model answers, trace, latency, and errors for one batch.
- `results.json` / `results.csv`: structured per-Case scores and release Gate.
- `insights.json`: failure definitions, priorities, owners, actions, and regression set.
- `algorithm-report.md` / `report.html`: team handoff and visual drill-down.
