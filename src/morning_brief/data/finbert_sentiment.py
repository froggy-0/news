"""FinBERT 감성 분석 모듈.

ProsusAI/finbert를 사용하여 영문 금융 텍스트의 감성 점수를 산출한다.
transformers/torch가 미설치된 환경에서도 ImportError 없이 동작하며,
모든 에러 경로에서 파이프라인을 중단하지 않는다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from math import ceil
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from morning_brief.config import Settings
    from morning_brief.observability import PipelineObserver

logger = logging.getLogger(__name__)

_TORCH_AVAILABLE: bool | None = None
_DEPS_WARNING_EMITTED = False


def _check_deps() -> bool:
    global _TORCH_AVAILABLE
    if _TORCH_AVAILABLE is None:
        try:
            import torch as _torch  # noqa: F401
            import transformers as _transformers  # noqa: F401

            _TORCH_AVAILABLE = True
        except ImportError:
            _TORCH_AVAILABLE = False
    return _TORCH_AVAILABLE


@dataclass
class SentimentResult:
    score: float | None
    confidence: float | None
    label: str | None


_NONE_RESULT = SentimentResult(score=None, confidence=None, label=None)

_MAX_TOTAL_TOKENS = 512
_MAX_ITEMS_LIMIT = 120
_XSIGNAL_SLOT_RATIO = 0.20
_XSIGNAL_SLOT_MAX = 24


def _first_non_empty(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


class FinBertScorer:
    """Lazy-loaded FinBERT scorer."""

    def __init__(self, settings: Settings) -> None:
        self._model: Any = None
        self._tokenizer: Any = None
        self._available: bool | None = None
        self._settings = settings

    def _ensure_loaded(self) -> bool:
        if self._available is not None:
            return self._available

        if not _check_deps():
            self._available = False
            return False

        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            model_id = self._settings.finbert_model_path or self._settings.finbert_model
            revision = self._settings.finbert_model_revision or None
            kwargs: dict[str, Any] = {}
            if revision:
                kwargs["revision"] = revision
            if self._settings.finbert_model_path:
                kwargs.pop("revision", None)

            self._tokenizer = AutoTokenizer.from_pretrained(model_id, **kwargs)
            self._model = AutoModelForSequenceClassification.from_pretrained(model_id, **kwargs)
            self._model.eval()
            self._available = True
        except Exception:
            logger.warning("FinBERT 모델 로드 실패 — 감성 점수를 건너뜁니다", exc_info=True)
            self._available = False

        return self._available

    def score_texts(
        self,
        texts: list[str],
        observer: PipelineObserver | None = None,
    ) -> list[SentimentResult]:
        if not texts:
            return []

        empty_mask = [not t or not t.strip() for t in texts]
        non_empty_texts = [t for t, is_empty in zip(texts, empty_mask) if not is_empty]

        if not non_empty_texts:
            return [_NONE_RESULT] * len(texts)

        if not self._ensure_loaded():
            return [_NONE_RESULT] * len(texts)

        try:
            import torch

            results_map: list[SentimentResult] = []
            batch_size = self._settings.finbert_batch_size
            t0 = time.perf_counter()

            for start in range(0, len(non_empty_texts), batch_size):
                batch = non_empty_texts[start : start + batch_size]
                inputs = self._tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=_MAX_TOTAL_TOKENS,
                    return_tensors="pt",
                )
                with torch.no_grad():
                    outputs = self._model(**inputs)
                probs = torch.nn.functional.softmax(outputs.logits, dim=-1)

                for prob in probs:
                    p_pos = prob[0].item()
                    p_neg = prob[1].item()
                    p_neu = prob[2].item()
                    score = round(p_pos - p_neg, 4)
                    confidence = round(max(p_pos, p_neg, p_neu), 4)
                    label = self._score_to_label(score)
                    results_map.append(
                        SentimentResult(score=score, confidence=confidence, label=label)
                    )

            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            scores_only = [r.score for r in results_map if r.score is not None]
            if observer and scores_only:
                observer.log_event(
                    "finbert_inference_complete",
                    message=f"FinBERT 추론 완료: {len(scores_only)}건, {elapsed_ms}ms",
                    count=len(scores_only),
                    duration_ms=elapsed_ms,
                    score_mean=round(sum(scores_only) / len(scores_only), 4),
                    score_min=round(min(scores_only), 4),
                    score_max=round(max(scores_only), 4),
                )

            final: list[SentimentResult] = []
            non_empty_idx = 0
            for is_empty in empty_mask:
                if is_empty:
                    final.append(_NONE_RESULT)
                else:
                    final.append(results_map[non_empty_idx])
                    non_empty_idx += 1
            return final

        except Exception:
            logger.warning("FinBERT 추론 실패 — 감성 점수를 None으로 설정합니다", exc_info=True)
            return [_NONE_RESULT] * len(texts)

    def _score_to_label(self, score: float) -> str:
        if score >= self._settings.finbert_bullish_threshold:
            return "bullish"
        if score <= self._settings.finbert_bearish_threshold:
            return "bearish"
        return "neutral"

    @staticmethod
    def combine_fields(
        *fields: str,
        max_tokens_per_field: tuple[int, ...] = (64, 224, 224),
    ) -> str:
        parts: list[str] = []
        for i, field in enumerate(fields):
            text = (field or "").strip()
            if not text:
                continue
            limit = (
                max_tokens_per_field[i]
                if i < len(max_tokens_per_field)
                else max_tokens_per_field[-1]
            )
            words = text.split()
            token_estimate = len(words)
            if token_estimate > limit:
                words = words[:limit]
            parts.append(" ".join(words))

        combined = " ".join(parts)
        words = combined.split()
        if len(words) > _MAX_TOTAL_TOKENS:
            words = words[:_MAX_TOTAL_TOKENS]
        return " ".join(words)


def _select_items_for_scoring(
    items: list[dict[str, Any]],
    max_items: int = _MAX_ITEMS_LIMIT,
) -> tuple[list[int], list[int]]:
    """120건 초과 시 sourceTier + 카테고리 비례 할당으로 선정.

    Returns (selected_indices, skipped_indices).
    """
    if len(items) <= max_items:
        return list(range(len(items))), []

    logger.warning(
        "FinBERT 추론 대상 %d건이 %d건 상한을 초과 — 우선순위 기반 선정",
        len(items),
        max_items,
    )

    indexed = list(enumerate(items))
    indexed.sort(key=lambda x: 0 if x[1].get("source_tier", "standard") == "tier1" else 1)

    by_cat: dict[str, list[int]] = {}
    for idx, item in indexed:
        cat = item.get("topic") or item.get("category") or "other"
        by_cat.setdefault(cat, []).append(idx)

    total = sum(len(v) for v in by_cat.values())
    selected: list[int] = []
    for cat, indices in by_cat.items():
        alloc = max(1, round(max_items * len(indices) / total))
        selected.extend(indices[:alloc])

    selected = selected[:max_items]
    selected_set = set(selected)
    skipped = [i for i in range(len(items)) if i not in selected_set]
    return selected, skipped


def build_news_sentiment_text(item: dict[str, Any]) -> str:
    return FinBertScorer.combine_fields(
        str(item.get("title", "")),
        str(item.get("summary", "")),
        str(item.get("why_it_matters", "")),
    )


def build_public_news_sentiment_text(item: dict[str, Any]) -> str:
    title = _first_non_empty(item.get("rawTitle"), item.get("title"))
    summary = _first_non_empty(
        item.get("rawSummary"),
        item.get("summaryKo"),
        item.get("summary_ko"),
        item.get("summary"),
    )
    interpretation = _first_non_empty(
        item.get("rawInterpretation"),
        item.get("interpretation"),
        item.get("interpretation_ko"),
        item.get("why_it_matters"),
    )
    return FinBertScorer.combine_fields(title, summary, interpretation)


def build_public_signal_sentiment_text(item: dict[str, Any]) -> str:
    content = _first_non_empty(
        item.get("rawContent"),
        item.get("content"),
        item.get("summary"),
        item.get("headline"),
    )
    impact = _first_non_empty(
        item.get("impact"),
        item.get("why_it_matters"),
    )
    return FinBertScorer.combine_fields(content, impact)


def enrich_news_packet(
    items: list[dict[str, Any]],
    settings: Settings,
    observer: PipelineObserver | None = None,
    *,
    text_builder: Callable[[dict[str, Any]], str] | None = None,
) -> str:
    """news_packet의 각 항목에 sentiment_score/confidence 부여.

    Returns: "ok" | "skipped" | "failed"
    """
    if not settings.finbert_enabled:
        return "skipped"

    global _DEPS_WARNING_EMITTED
    if not _check_deps():
        if not _DEPS_WARNING_EMITTED:
            logger.warning("transformers/torch 미설치 — FinBERT 감성 분석을 건너뜁니다")
            _DEPS_WARNING_EMITTED = True
        return "skipped"

    if not items:
        return "skipped"

    try:
        scorer = FinBertScorer(settings)
        text_builder = text_builder or build_news_sentiment_text

        selected, skipped = _select_items_for_scoring(items)

        texts = [text_builder(items[i]) for i in selected]

        if observer:
            with observer.phase("finbert"):
                results = scorer.score_texts(texts, observer)
        else:
            results = scorer.score_texts(texts)

        for sel_idx, result in zip(selected, results):
            items[sel_idx]["sentiment_score"] = result.score
            items[sel_idx]["sentiment_confidence"] = result.confidence

        for skip_idx in skipped:
            items[skip_idx]["sentiment_score"] = None
            items[skip_idx]["sentiment_confidence"] = None

        return "ok"
    except Exception:
        logger.warning("FinBERT enrichment 실패", exc_info=True)
        for item in items:
            item.setdefault("sentiment_score", None)
            item.setdefault("sentiment_confidence", None)
        return "failed"


def enrich_x_signals(
    signals: list[Any],
    settings: Settings,
    observer: PipelineObserver | None = None,
) -> None:
    """XSignal 객체에 sentiment_score/confidence 직접 부여."""
    if not settings.finbert_enabled or not _check_deps() or not signals:
        return

    try:
        scorer = FinBertScorer(settings)

        max_signals = min(
            len(signals),
            _XSIGNAL_SLOT_MAX,
            ceil(len(signals) * _XSIGNAL_SLOT_RATIO)
            if len(signals) > _XSIGNAL_SLOT_MAX
            else len(signals),
        )
        process_signals = signals[:max_signals]

        texts = [
            scorer.combine_fields(
                getattr(s, "headline", "") or "",
                getattr(s, "summary", "") or "",
                getattr(s, "why_it_matters", "") or "",
            )
            for s in process_signals
        ]

        results = scorer.score_texts(texts, observer)

        for sig, result in zip(process_signals, results):
            sig.sentiment_score = result.score
            sig.sentiment_confidence = result.confidence

    except Exception:
        logger.warning("FinBERT XSignal enrichment 실패", exc_info=True)


def enrich_public_signal_items(
    items: list[dict[str, Any]],
    settings: Settings,
    observer: PipelineObserver | None = None,
) -> str:
    return enrich_news_packet(
        items,
        settings,
        observer,
        text_builder=build_public_signal_sentiment_text,
    )


__all__ = [
    "FinBertScorer",
    "SentimentResult",
    "build_news_sentiment_text",
    "build_public_news_sentiment_text",
    "build_public_signal_sentiment_text",
    "enrich_news_packet",
    "enrich_public_signal_items",
    "enrich_x_signals",
]
