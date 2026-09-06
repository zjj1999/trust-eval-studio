---
name: trust-eval-pm
description: Turn product feedback or model Q/A batches into high-value case samples, PM-reviewed eval sets, automated trust evaluations, and actionable product insights. Use when a PM asks to select representative cases, co-create ground truth or rubrics, run TrustEval, compare a model batch, decide whether it can ship, or identify what to optimize. Do not auto-approve draft rubrics for production.
---

# TrustEval PM

Operate the TrustEval Studio repository as a PM-facing evaluation copilot. Keep the workflow auditable and leave high-value product decisions to the PM.

## Locate the project

Work from the repository containing `pyproject.toml` and `src/trust_eval`. If the `trust-eval` command is not installed, invoke it as:

```bash
PYTHONPATH=src python3 -m trust_eval ...
```

## Choose the smallest relevant mode

- **Select cases:** Use when the input is a large production-feedback export and the PM needs a small valuable batch. Run `collect`; explain why each selected Case matters using its value score and reasons.
- **Co-create an eval set:** Use when the input has questions and model answers but lacks ground truth or rubrics. Run `build`, then surface `review.csv` for PM or expert confirmation.
- **Evaluate a model batch:** Use when `cases.jsonl` is already approved. Run `evaluate` against existing answers, an HTTP model Endpoint, or an explicitly authorized internal command.
- **Generate insights:** Use `report` when scores already exist and only the product/algorithm interpretation must be refreshed.
- **Expose a service:** Use `serve` when another PM tool or internal platform needs HTTP access. Read [references/contracts.md](references/contracts.md) for endpoints and safety constraints.

## Default workflow

1. Inspect the input fields and identify whether it is raw business feedback, a drafted eval set, or an approved eval set.
2. For business feedback, run `collect --policy balanced` unless the PM explicitly prioritizes risk or representativeness. Preserve PM-nominated cases.
3. Run `build` on the selected Case file. Treat existing model answers as candidates to evaluate, never as ground truth.
4. Stop at the human review Gate when standards are drafts. Ask the PM to confirm expected behavior, factual references, three-lens standards, and release red lines. Never use `--approve-demo` for a real release decision.
5. After approval, run `evaluate`. Keep deterministic red-line checks enabled; add an LLM Judge only when credentials and the intended model are explicitly configured.
6. Lead the handoff with two answers: **Can this batch ship?** and **What should be fixed first?** Link every optimization conclusion to issue codes and representative Case IDs.

## Product interpretation rules

- Red lines cannot be averaged away by a high total score.
- `unknown` means missing evidence or an unresolved Judge result, not model success.
- A targeted eval-set pass rate describes this batch only; do not present it as production incidence.
- Prioritize optimization by severity, affected Case count, and user/business impact. State the failure definition, responsible direction, action, and success criterion.
- Preserve dataset fingerprint, rubric version, target-model batch, and Judge identity when comparing iterations.

## Operational boundaries

- Keep API keys in environment variables; never place secrets in commands, files, reports, or chat output.
- Do not expose the service beyond localhost without `TRUST_EVAL_API_TOKEN`.
- The HTTP service intentionally rejects arbitrary command execution. Use command adapters only from a trusted local CLI session.
- Do not publish or send evaluation data outside the requested scope without explicit authorization.
