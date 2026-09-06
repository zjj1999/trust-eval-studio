from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .io import normalize_records, read_cases
from .rubric import infer_category


SAMPLING_PRESETS: dict[str, dict[str, float]] = {
    "balanced": {
        "risk": 0.30,
        "negative_feedback": 0.25,
        "frequency": 0.20,
        "uncertainty": 0.15,
        "recency": 0.10,
    },
    "risk-first": {
        "risk": 0.45,
        "negative_feedback": 0.25,
        "frequency": 0.10,
        "uncertainty": 0.15,
        "recency": 0.05,
    },
    "representative": {
        "risk": 0.15,
        "negative_feedback": 0.20,
        "frequency": 0.40,
        "uncertainty": 0.10,
        "recency": 0.15,
    },
}

RISK_BY_CATEGORY = {
    "safety": 1.0,
    "action_integrity": 0.9,
    "input_grounding": 0.85,
    "factual_correction": 0.7,
    "reasoning_intent": 0.5,
    "general": 0.35,
}


class FeedbackSource(Protocol):
    """Adapter contract for production feedback streams."""

    name: str

    def fetch(self, *, since: str | None = None, limit: int = 1000) -> list[dict[str, Any]]: ...


@dataclass
class FileFeedbackSource:
    path: str | Path
    name: str = "file-feedback"

    def fetch(self, *, since: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        del since
        return read_cases(self.path)[:limit]


@dataclass
class HttpFeedbackSource:
    """Generic placeholder adapter for a future Doubao production feedback API."""

    endpoint: str
    api_key_env: str = "FEEDBACK_API_KEY"
    timeout: int = 60
    name: str = "http-feedback"

    def fetch(self, *, since: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        headers = {"Content-Type": "application/json"}
        api_key = os.environ.get(self.api_key_env)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        body = json.dumps({"since": since, "limit": limit}, ensure_ascii=False).encode()
        request = urllib.request.Request(self.endpoint, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise RuntimeError(f"feedback endpoint HTTP {exc.code}: {detail}") from exc
        records = _records_from_payload(payload)
        return normalize_records(records[:limit], f"feedback-api:{self.endpoint}")


@dataclass
class SamplingPolicy:
    top_k: int = 50
    preset: str = "balanced"
    max_per_category: int | None = None
    min_score: float = 0.0
    deduplicate: bool = True

    def __post_init__(self) -> None:
        if self.preset not in SAMPLING_PRESETS:
            raise ValueError(f"未知选样策略 {self.preset}；可选 {', '.join(SAMPLING_PRESETS)}")
        if self.top_k < 1:
            raise ValueError("top_k 必须大于 0")
        if self.max_per_category is not None and self.max_per_category < 1:
            raise ValueError("max_per_category 必须大于 0")


def _records_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("records", "items", "cases", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    raise ValueError("业务回流接口必须返回数组，或包含 records/items/cases/data 数组")


def _extra(case: dict[str, Any]) -> dict[str, Any]:
    value = case.get("context", {}).get("extra", {})
    return value if isinstance(value, dict) else {}


def _first(case: dict[str, Any], *keys: str) -> Any:
    extra = _extra(case)
    for key in keys:
        if key in extra and extra[key] not in (None, ""):
            return extra[key]
        if key in case and case[key] not in (None, ""):
            return case[key]
    return None


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "是",
        "人工提名",
        "thumbs_down",
        "negative",
    }


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _negative_feedback(case: dict[str, Any]) -> float:
    explicit = _first(case, "negative_feedback", "thumbs_down", "disliked", "is_negative")
    if explicit is not None:
        return 1.0 if _truthy(explicit) else 0.0
    sentiment = str(_first(case, "sentiment", "feedback_sentiment") or "").lower()
    if any(token in sentiment for token in ("negative", "bad", "dissatisfied", "负向", "不满意")):
        return 1.0
    rating = _number(_first(case, "rating", "csat", "user_rating"), -1)
    if rating < 0:
        return 0.0
    scale = max(_number(_first(case, "rating_scale", "csat_scale"), 5), 1)
    return _clamp(1 - rating / scale)


def _uncertainty(case: dict[str, Any]) -> float:
    if _truthy(_first(case, "needs_review", "model_uncertain", "low_confidence")):
        return 1.0
    confidence = _number(_first(case, "confidence", "model_confidence"), -1)
    if confidence >= 0:
        return _clamp(1 - confidence)
    answer = str(case.get("answer", ""))
    if not answer.strip():
        return 1.0
    if re.search(r"不确定|无法确认|可能|也许|I('m| am) not sure", answer, re.I):
        return 0.65
    return 0.15


def _recency(case: dict[str, Any], now: datetime) -> float:
    raw = _first(case, "timestamp", "created_at", "event_time", "feedback_time")
    if not raw:
        return 0.5
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (now - parsed.astimezone(timezone.utc)).total_seconds() / 86400)
        return math.exp(-age_days / 30)
    except ValueError:
        return 0.5


def _manual_priority(case: dict[str, Any]) -> bool:
    return _truthy(_first(case, "manual_priority", "pm_nominated", "pinned", "must_select"))


def _fingerprint(case: dict[str, Any]) -> str:
    text = str(case.get("query", "")).lower()
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text)[:240]


def _selection_reason(features: dict[str, float], pinned: bool) -> list[str]:
    labels = {
        "risk": "高风险场景",
        "negative_feedback": "用户负反馈",
        "frequency": "线上高频",
        "uncertainty": "模型或证据不确定",
        "recency": "近期新增",
    }
    reasons = [labels[key] for key, value in features.items() if value >= 0.65]
    if pinned:
        reasons.insert(0, "PM 人工提名")
    return reasons or ["补充场景覆盖"]


def select_valuable_cases(
    cases: list[dict[str, Any]],
    policy: SamplingPolicy | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Rank feedback cases by product value, then preserve category diversity."""

    resolved = policy or SamplingPolicy()
    weights = SAMPLING_PRESETS[resolved.preset]
    now = datetime.now(timezone.utc)
    frequencies = [
        max(1.0, _number(_first(case, "occurrence_count", "frequency", "volume", "count"), 1.0))
        for case in cases
    ]
    max_frequency = max(frequencies, default=1.0)
    scored: list[dict[str, Any]] = []
    for case, raw_frequency in zip(cases, frequencies):
        category = infer_category(case)
        features = {
            "risk": RISK_BY_CATEGORY.get(category, 0.35),
            "negative_feedback": _negative_feedback(case),
            "frequency": _clamp(math.log1p(raw_frequency) / math.log1p(max_frequency)),
            "uncertainty": _uncertainty(case),
            "recency": _recency(case, now),
        }
        pinned = _manual_priority(case)
        score = sum(features[key] * weights[key] for key in weights)
        if pinned:
            score = max(score, 0.95)
        item = dict(case)
        item["selection"] = {
            "value_score": round(score * 100, 1),
            "policy": resolved.preset,
            "category": category,
            "features": {key: round(value, 3) for key, value in features.items()},
            "reasons": _selection_reason(features, pinned),
            "pm_nominated": pinned,
        }
        scored.append(item)

    scored.sort(
        key=lambda item: (
            not item["selection"]["pm_nominated"],
            -item["selection"]["value_score"],
            item["case_id"],
        )
    )
    unique: list[dict[str, Any]] = []
    duplicate_ids: list[str] = []
    seen: set[str] = set()
    for item in scored:
        fingerprint = _fingerprint(item)
        if resolved.deduplicate and fingerprint and fingerprint in seen:
            duplicate_ids.append(item["case_id"])
            continue
        seen.add(fingerprint)
        if item["selection"]["value_score"] >= resolved.min_score:
            unique.append(item)

    categories = {item["selection"]["category"] for item in unique}
    default_cap = max(2, math.ceil(resolved.top_k / max(1, len(categories))) + 1)
    cap = resolved.max_per_category or min(resolved.top_k, default_cap)
    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    category_counts: Counter[str] = Counter()
    for item in unique:
        category = item["selection"]["category"]
        if len(selected) < resolved.top_k and category_counts[category] < cap:
            selected.append(item)
            category_counts[category] += 1
        else:
            deferred.append(item)
    for item in deferred:
        if len(selected) >= resolved.top_k:
            break
        selected.append(item)
        category_counts[item["selection"]["category"]] += 1

    report = {
        "schema_version": "1.0",
        "policy": {
            "preset": resolved.preset,
            "top_k": resolved.top_k,
            "max_per_category": cap,
            "min_score": resolved.min_score,
            "deduplicate": resolved.deduplicate,
            "weights": weights,
        },
        "input_count": len(cases),
        "eligible_count": len(unique),
        "selected_count": len(selected),
        "duplicate_case_ids": duplicate_ids,
        "selected_distribution": dict(category_counts),
        "selected": [
            {
                "case_id": item["case_id"],
                "value_score": item["selection"]["value_score"],
                "category": item["selection"]["category"],
                "reasons": item["selection"]["reasons"],
            }
            for item in selected
        ],
    }
    return selected, report
