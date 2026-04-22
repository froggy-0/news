# Design Document: data-ingestion-quality-improvement

## Overview

8개 Requirements를 최소 변경 원칙으로 구현한다. 핵심 전략은 세 가지다: (1) provider 식별 상수를 단일 모듈로 통합해 런타임 namespace 혼재를 해소하고, (2) `NewsItem → dict` 경계에 `TypedDict`를 도입해 타입 안전성을 회복하며, (3) 품질 지표·dedup·필터 로직을 실제 데이터 분류(정형/반정형/비정형)에 맞게 강화한다. LLM 브리핑 생성·이메일 발송·프론트엔드 레이어는 수정하지 않는다.

코드 탐색에서 발견된 실제 문제:
- `GROK_KEYWORD_PROVIDER`가 `grok_x_keyword.py`에선 `"grok_keyword"`, `news_selection.py`에선 `"grok_x_keyword"`로 이중 정의됨 (circuit breaker와 data provenance namespace가 혼재)
- `OFFICIAL_SIGNAL_PROVIDER`가 `news_packet.py:9`와 `data_quality.py:15`에 중복 정의
- `prompting.py:92`가 `item["official_source"]` 외에 `item["provider"] == "grok_official_x"` 리터럴도 사용

---

## Architecture

```mermaid
graph TD
    subgraph 신규/변경 모듈
        P[providers.py<br/>단일 상수 출처]
        NPI[NewsPacketItem TypedDict<br/>in news_packet.py]
        CTL[cache TTL 체크<br/>in market.py]
        CZR[카테고리별 zero_ratio<br/>in data_quality.py]
        YAML[domain_policy.yaml<br/>+ news_policy.py loader]
    end

    subgraph 기존 모듈 (참조만 변경)
        DQ[data_quality.py]
        NS[news_selection.py]
        NP[news_packet.py]
        GXK[grok_x_keyword.py]
        NK[news.py]
    end

    P -->|임포트| DQ
    P -->|임포트| NS
    P -->|임포트| NP
    P -->|임포트| GXK
    NPI -->|반환 타입| NP
    NPI -->|typed access| DQ
    CTL -->|staleness 경고| market.py
    CZR -->|카테고리 분리| DQ
    YAML -->|로드 fallback| news_policy.py
```

### 변경 파일 목록

| 파일 | 변경 유형 | Requirement |
|------|---------|-------------|
| `src/morning_brief/data/providers.py` | **신규** | R1 |
| `src/morning_brief/data/news_packet.py` | 수정 (TypedDict 추가, 임포트 변경) | R1, R2 |
| `src/morning_brief/data/news_selection.py` | 수정 (임포트, 상수 제거, dedup 강화, 패턴 확장) | R1, R5, R7 |
| `src/morning_brief/data/data_quality.py` | 수정 (임포트, 카테고리 zero_ratio) | R1, R4 |
| `src/morning_brief/data/sources/grok_x_keyword.py` | 수정 (임포트, GROK_KEYWORD_PROVIDER 제거) | R1 |
| `src/morning_brief/data/market.py` | 수정 (캐시 TTL, cached_at) | R3 |
| `src/morning_brief/config.py` | 수정 (Settings 필드 추가) | R3 |
| `src/morning_brief/data/news.py` | 수정 (XSignal dedup 추가) | R6 |
| `src/morning_brief/data/news_policy.py` | 수정 (YAML 로더 추가) | R8 |
| `config/domain_policy.yaml` | **신규** | R8 |

---

## Components and Interfaces

### R1 — `providers.py` (신규)

```python
# src/morning_brief/data/providers.py
"""파이프라인 전체에서 사용하는 provider 식별 상수의 단일 출처.

두 가지 namespace를 명시적으로 구분한다:
- DATA_PROVIDER_*: NewsItem.provider 필드에 기록되는 데이터 출처 식별자
- RUNTIME_PROVIDER_*: provider_runtime.py circuit breaker가 사용하는 운영 식별자
  (logging_utils.py의 정규화 맵과 일치해야 함)
"""

# ── Data provenance (NewsItem.provider 값) ──────────────────────────
PERPLEXITY_SEARCH   = "perplexity_search"
PERPLEXITY_SONAR    = "perplexity_sonar"
GROK_OFFICIAL_X     = "grok_official_x"
GROK_X_KEYWORD      = "grok_x_keyword"   # grok_x_keyword.py line 298에서 실제 설정되는 값
GROK_WEB_SEARCH     = "grok_web_search"

# ── Runtime circuit breaker (provider_runtime.py ProviderPolicy.name) ──
RUNTIME_GROK_KEYWORD = "grok_keyword"    # circuit breaker 정책 키 (grok_x_keyword.py:32 기존 값)

# ── 집합 (분류용) ───────────────────────────────────────────────────
PERPLEXITY_PROVIDERS: frozenset[str] = frozenset({PERPLEXITY_SEARCH, PERPLEXITY_SONAR})
GROK_PROVIDERS: frozenset[str] = frozenset({GROK_OFFICIAL_X, GROK_X_KEYWORD, GROK_WEB_SEARCH})
```

**Design Decision:** circuit breaker용 `"grok_keyword"`와 NewsItem provenance용 `"grok_x_keyword"`는 다른 값을 유지한다. `logging_utils.py`의 정규화 맵이 이미 두 값을 `"grok_keyword"`로 수렴시키고 있으므로 변경 시 해당 맵도 함께 수정해야 한다. 이번 작업은 두 값의 존재를 명시적으로 문서화하는 것으로 충분하다.

**Circular import 방지 조건:** `providers.py`는 `stdlib`과 `typing`만 임포트한다. `news_packet.py`, `news_selection.py`, `data_quality.py`, `grok_x_keyword.py` 모두 `providers.py`에 의존하므로, `providers.py`가 이들 중 어느 하나라도 역방향 임포트하면 순환 참조가 발생한다. **`providers.py`는 내부 모듈을 임포트해서는 안 된다.**

**기존 코드 마이그레이션:**
- `news_packet.py`: `OFFICIAL_SIGNAL_PROVIDER`, `GROK_PROVIDERS` → `providers.GROK_OFFICIAL_X`, `providers.GROK_PROVIDERS`
- `news_selection.py`: 모든 provider 상수 → `providers.*` 임포트
- `data_quality.py`: 모든 provider 상수 → `providers.*` 임포트
- `grok_x_keyword.py`: `GROK_KEYWORD_PROVIDER = "grok_keyword"` → `providers.RUNTIME_GROK_KEYWORD`
- `prompting.py:92`: `"grok_official_x"` 리터럴 → `providers.GROK_OFFICIAL_X`

---

### R2 — `NewsPacketItem` TypedDict (`news_packet.py` 수정)

```python
# src/morning_brief/data/news_packet.py
from typing import TypedDict

class NewsPacketItem(TypedDict):
    title: str
    url: str
    source: str
    published_at: str | None          # ISO 8601 or None
    domain: str
    source_tier: str                   # "tier_1" | "tier_2" | "tier_3"
    preferred_source: bool
    age_hours: float | None
    topic: str | None
    provider: str | None
    summary: str | None
    why_it_matters: str | None
    citations: list[str]
    official_source: bool

def news_items_to_packet(items: list[NewsItem]) -> list[NewsPacketItem]:
    ...  # 구현 변경 없음, 반환 타입만 변경
```

**Design Decision:** `TypedDict`는 런타임에 일반 `dict`와 완전히 호환된다. `briefing.py`, `emailer.py`, `public_site.py` 등 기존 소비자들의 `.get("key")` 접근 패턴은 수정 없이 동작한다. mypy는 `TypedDict` 키 접근에 대한 타입 오류를 정적 분석 시 감지한다.

`data_quality.py`에서 `item.get("age_hours")` → `item["age_hours"]`로 변경해 mypy가 `Optional[float]`를 추적하게 한다.

**mypy 커버 범위 주의:** `pyproject.toml`의 `[tool.mypy] files`에는 `data_quality.py`, `market.py`만 포함되고 `news_packet.py`, `news_selection.py`, `providers.py`는 미포함이다. R2의 TypedDict 타입 검증 효과를 얻으려면 **`providers.py`와 `news_packet.py`를 mypy `files` 목록에 추가해야 한다.** 추가하지 않으면 TypedDict 선언은 존재하지만 mypy가 소비자 코드를 검사하지 않아 R2의 핵심 목적이 달성되지 않는다.

---

### R3 — 시장 캐시 TTL (`market.py`, `config.py` 수정)

**캐시 파일 구조 변경:**
```json
// 기존: { "btc_usd": {...}, "us10y": {...} }
// 변경: { "_meta": {"cached_at": "2026-04-04T08:00:00+00:00"}, "btc_usd": {...}, "us10y": {...} }
```

```python
# config.py Settings 필드 추가 (frozen dataclass이므로 load_settings()에도 추가)
market_point_cache_max_age_hours: int  # 기본값 26

# market.py
MARKET_POINT_CACHE_MAX_AGE_HOURS = 26  # Settings 없는 호출 경로용 기본값

def _save_market_point_cache(cache_file: Path, points: list[MarketPoint]) -> None:
    payload = {
        "_meta": {"cached_at": datetime.now(timezone.utc).isoformat()},
        # 기존 per-point 직렬화...
    }
    ...

def _load_market_point_cache(
    cache_file: Path,
    *,
    max_age_hours: int = MARKET_POINT_CACHE_MAX_AGE_HOURS,
) -> dict[str, MarketPoint]:
    ...
    meta = payload.pop("_meta", {})
    cached_at_raw = meta.get("cached_at") if isinstance(meta, dict) else None
    if cached_at_raw:
        try:
            cached_at = datetime.fromisoformat(cached_at_raw)
            age_hours = (datetime.now(timezone.utc) - cached_at).total_seconds() / 3600
            if age_hours > max_age_hours:
                log_structured(logger, event="cache.stale", level=logging.WARNING,
                               message="시장 포인트 캐시가 오래됐어요. 가져오지 못한 값에 stale 데이터가 사용될 수 있어요.",
                               age_hours=round(age_hours, 1), max_age_hours=max_age_hours)
        except ValueError:
            pass
    ...
```

**Design Decision:** 캐시 중단 없이 경고만 남긴다. live fetch 실패 시 stale 캐시라도 사용하는 것이 빈 값보다 브리핑 품질에 유리하다. `_meta` 키가 없는 기존 캐시는 staleness 판정 없이 기존 방식대로 동작한다.

**2개의 호출 경로 처리:**
- `build_market_packet` (pipeline.py 경로): `settings` 객체 있음 → `_load_market_point_cache(cache_file, max_age_hours=settings.market_point_cache_max_age_hours)` 로 호출
- `fetch_newsletter_display_data` (pipeline.py:296, settings 없음): `_load_market_point_cache(cache_file)` — `max_age_hours` 파라미터 기본값(`MARKET_POINT_CACHE_MAX_AGE_HOURS = 26`)으로 동작. 이 경로는 뉴스레터 렌더링 직전 호출이므로 `build_market_packet`이 이미 캐시를 갱신한 직후 실행됨. stale 경고가 발생하더라도 운영상 허용 가능하며 settings 주입 리팩터는 이번 범위 밖으로 한다.

---

### R4 — 카테고리별 zero_ratio (`data_quality.py` 수정)

현재 `_zero_ratio(packet: dict) -> float` 구조를 분리한다:

```python
def _zero_ratio_by_category(packet: dict) -> dict[str, float]:
    """카테고리별로 가격 누락 비율을 계산한다.

    bitcoin 카테고리 주의: build_market_packet 경로에서 etf_points는 항상 []
    (fetch_etf_prices=False로 호출 — market.py:958). bitcoin zero_ratio는
    spot 단일 포인트(1개)만으로 판정됨. 따라서 bitcoin = 0.0 또는 1.0 이진값.
    fetch_newsletter_display_data 경로에서는 etf_points가 5개 포함되지만,
    해당 경로는 data_quality 체크 경로가 아니므로 영향 없음.
    """
    categories = {
        "macro":   packet.get("macro", []),
        "indices": packet.get("us_indices", []),
        "tech":    packet.get("tech_stocks", []),
        "bitcoin": [packet.get("bitcoin", {}).get("spot", {})]
                   + packet.get("bitcoin", {}).get("etf_points", []),
    }
    result: dict[str, float] = {}
    for cat, points in categories.items():
        valid = [p for p in points if isinstance(p, dict)]
        if not valid:
            result[cat] = 0.0
            continue
        zero = [p for p in valid if _safe_price(p.get("price", 0.0)) <= 0.0]
        result[cat] = round(len(zero) / len(valid), 4)
    return result

def _zero_ratio(packet: dict) -> float:
    """전체 zero_ratio (하위 호환용). 카테고리별 최댓값을 반환한다."""
    by_cat = _zero_ratio_by_category(packet)
    return max(by_cat.values(), default=1.0)
```

**Design Decision:** 가중 평균 대신 **카테고리 최댓값**을 전체 `zero_ratio`로 사용한다. 이유: "macro가 100% 누락"이면 브리핑 품질에 치명적인데 가중 평균은 이를 희석한다. 기존 critical 임계값(`zero_ratio >= 0.8`)은 유지된다.

`assess_data_quality` 반환값에 `"zero_ratio_by_category"` 추가:
```python
return {
    ...
    "zero_price_ratio": round(_zero_ratio(packet), 4),  # 기존 키 유지
    "zero_ratio_by_category": _zero_ratio_by_category(packet),  # 신규
    ...
}
```

---

### R5 — 뉴스 제목 보조 dedup (`news_selection.py` 수정)

`_dedup_and_rank` 내 `by_key` dict에 보조 키 맵을 추가한다:

```python
def _title_dedup_key(title: str) -> str:
    """제목 앞 40자를 소문자·공백 정규화한 dedup 키.
    10자 미만이면 빈 문자열 반환 → 보조 dedup 비활성화.
    """
    normalized = " ".join(title.strip().lower().split())
    if len(normalized) < 10:
        return ""
    return normalized[:40]

def _dedup_and_rank(items, max_items, *, min_output=0):
    by_url: dict[str, NewsItem] = {}
    by_title: dict[str, str] = {}  # title_key → url_key (항상 by_url의 현재 키와 동기화)

    for item in items:
        ...
        url_key = normalized_url or title.lower()
        title_key = _title_dedup_key(title)

        # title 충돌 확인: 이미 다른 URL로 같은 제목이 있으면 점수 비교
        existing_url_key = by_title.get(title_key) if title_key else None
        if existing_url_key and existing_url_key != url_key:
            existing = by_url.get(existing_url_key)
            if existing and _item_score(normalized_item) <= _item_score(existing):
                continue  # 기존 것이 더 좋음 → 스킵 (by_url, by_title 변경 없음)
            else:
                # 신규가 더 좋음 → 기존 url_key 제거 후 즉시 신규로 교체
                # 주의: del by_url[existing_url_key] 직후 by_title[title_key]은
                # 아직 existing_url_key를 가리키지만, 바로 아래 줄에서 갱신됨.
                # by_title 갱신은 반드시 by_url 갱신과 같은 블록에서 이루어져야 함.
                del by_url[existing_url_key]
                # fall through → 아래에서 by_url[url_key]와 by_title[title_key] 동시 갱신

        by_url[url_key] = normalized_item
        if title_key:
            by_title[title_key] = url_key  # by_url과 항상 동기화
    ...
```

**Design Decision:** 제목 앞 40자를 기준으로 한다. 짧은 제목(< 10자) dedup은 오탐 위험이 높으므로 `_title_dedup_key`가 빈 문자열을 반환해 보조 dedup을 비활성화한다.

**`by_title` 동기화 불변식:** `by_title[title_key]`가 가리키는 `url_key`는 항상 `by_url`에 현재 존재하는 키여야 한다. `del by_url[key]`는 반드시 `by_title[title_key] = new_url_key` 갱신과 짝을 이루어야 한다. 두 갱신 사이 중간 상태(dangling reference)는 단일 iteration 내에서만 존재하며, 외부에서 접근 불가하므로 허용된다.

---

### R6 — XSignal dedup (`news.py` 수정)

```python
# src/morning_brief/data/news.py
def _dedup_x_signals(signals: list[XSignal]) -> list[XSignal]:
    """source_handle + headline[:30] 복합 키로 중복 XSignal을 제거한다."""
    seen: dict[str, XSignal] = {}
    removed = 0

    for signal in signals:
        handle = (signal.source_handle or "").strip().lower()
        headline_prefix = " ".join((signal.headline or "").strip().lower().split())[:30]
        key = f"{handle}:{headline_prefix}"

        existing = seen.get(key)
        if existing is None:
            seen[key] = signal
        else:
            # posted_at이 더 최신인 것으로 교체 (없으면 기존 유지)
            existing_at = existing.posted_at
            signal_at = signal.posted_at
            if signal_at and (existing_at is None or signal_at > existing_at):
                seen[key] = signal  # 교체: 기존 버림

    # removed = 입력 - 출력 (실제 제거된 signal 수)
    removed = len(signals) - len(seen)
    if removed > 0:
        log_structured(logger, event="dedup.applied", level=logging.DEBUG,
                       message="중복 X 시그널을 정리했어요.",
                       provider="x_signal", removed_count=removed)
    return list(seen.values())
```

`build_news_packet` 내 `_cap_signals_by_topic` 호출 전에 적용:
```python
public_ranked_signals = _cap_signals_by_topic(
    _dedup_x_signals(x_signals),  # dedup 먼저
    total_max=PUBLIC_ALL_X_SIGNALS,
    per_topic_max=4,
)
```

**Design Decision:** `XSignal.source_handle`은 동일 계정의 반복을 잡고, `headline[:30]`은 다른 계정이 동일 사건을 올린 경우를 잡는다. 두 조건의 AND이므로 오탐이 낮다.

---

### R7 — 다국어 meaningless interpretation 탐지 (`news_selection.py` 수정)

```python
_PUBLIC_NEWS_MEANINGLESS_INTERPRETATIONS = frozenset(
    {
        # 한국어 (기존)
        "", "없음", "없음.", "없음,", "해당없음", "해당 없음",
        "해당없음.", "해당 없음.", "해당없음,", "해당 없음,",
        # 영어 (신규)
        "n/a", "na", "none", "null", "unknown",
        "no information", "no comment", "not available",
        "no information available", "no details available",
        "–", "-", "...",
    }
)
```

`_has_meaningful_public_interpretation` 로직 강화:
```python
def _has_meaningful_public_interpretation(item: NewsItem) -> bool:
    interpretation = item.why_it_matters.strip() or item.summary.strip()
    normalized = _normalized_publish_text(interpretation)
    if not normalized:
        return False
    if normalized in _PUBLIC_NEWS_MEANINGLESS_INTERPRETATIONS:
        return False
    # 30자 미만 + 패턴 부분 포함 체크 (예: "N/A." → "n/a" 포함)
    if len(normalized) < 30:
        stripped = normalized.rstrip(".,;:")
        if stripped in _PUBLIC_NEWS_MEANINGLESS_INTERPRETATIONS:
            return False
    return True
```

**Design Decision:** 30자 미만 텍스트에만 부분 매칭을 적용한다. 긴 텍스트에서 "no" 등을 매칭하면 오탐이 발생한다.

---

### R8 — 도메인 정책 YAML 외부화 (`news_policy.py`, `config/domain_policy.yaml` 신규)

```yaml
# config/domain_policy.yaml
version: "1"
domains:
  - domain: "reuters.com"
    score: 5.0
    tier: "tier_1"
    score_rationale: "글로벌 1위 통신사, 편집 독립성 높음"
  - domain: "bloomberg.com"
    score: 5.0
    tier: "tier_1"
    score_rationale: "금융 전문 미디어, 신뢰도 최상위"
  # ... 기존 도메인 전체
```

```python
# news_policy.py 로더
# PyYAML이 requirements.txt에 없으므로 추가 필요 (현재 transitive dependency로만 존재)
import yaml  # PyYAML

def _load_domain_policy(config_path: Path | None = None) -> tuple[dict, dict, dict]:
    """(DOMAIN_SCORES, SOURCE_TIERS, PREFERRED_DOMAINS_set) 반환.
    YAML 없음 → WARNING + fallback. YAML 스키마 오류 → WARNING + fallback.
    어느 경우에도 파이프라인을 중단시키지 않는다.
    """
    path = config_path or _resolve_domain_policy_path()
    if not path.exists():
        log_structured(logger, event="config.fallback", level=logging.WARNING,
                       message="domain_policy.yaml이 없어 기본값을 사용할게요.",
                       path=str(path))
        return _HARDCODED_DOMAIN_SCORES, _HARDCODED_SOURCE_TIERS, _HARDCODED_PREFERRED_DOMAINS
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return _parse_domain_policy(raw)  # 스키마 검증 포함
    except Exception as exc:
        log_structured(logger, event="config.fallback", level=logging.WARNING,
                       message="domain_policy.yaml 파싱 실패, 기본값을 사용할게요.",
                       path=str(path), reason=str(exc))
        return _HARDCODED_DOMAIN_SCORES, _HARDCODED_SOURCE_TIERS, _HARDCODED_PREFERRED_DOMAINS

def _resolve_domain_policy_path() -> Path:
    """프로젝트 루트/config/domain_policy.yaml 절대 경로 반환.
    __file__ 기준으로 결정하므로 실행 디렉토리 무관."""
    return Path(__file__).parent.parent.parent.parent / "config" / "domain_policy.yaml"

# 모듈 임포트 시 자동 초기화 (스케줄러 재시작 없이 YAML 변경 불가 — 의도된 동작)
DOMAIN_SCORES, _SOURCE_TIERS_DICT, _PREFERRED_SET = _load_domain_policy()
SOURCE_TIERS = _SOURCE_TIERS_DICT
PREFERRED_DOMAINS = _PREFERRED_SET
```

**Design Decision:** YAML 없음과 스키마 오류 모두 WARNING + fallback으로 통일한다. 스키마 오류에서 ValueError로 파이프라인을 중단시키면 YAML 편집 실수 한 번에 매일 8시 브리핑이 불발된다. 운영 안정성이 엄격한 스키마 검증보다 우선한다.

**YAML 경로 결정 전략:** `Path(__file__)`을 사용해 `news_policy.py` 위치 기준으로 절대 경로를 계산한다. `CWD` 의존 방식(`Path("config/domain_policy.yaml")`)은 실행 위치에 따라 달라지므로 사용하지 않는다.

**PyYAML 의존성:** `requirements.txt`에 `PyYAML`이 없고 현재 transitive dependency로만 설치됨 (venv에 `pyyaml-6.0.3` 존재 확인). R8 구현 시 `requirements.txt`에 `PyYAML>=6.0` 명시 추가 필요.

---

## Data Models

### `NewsPacketItem` TypedDict

```python
class NewsPacketItem(TypedDict):
    title: str
    url: str
    source: str
    published_at: str | None
    domain: str
    source_tier: str          # Literal["tier_1", "tier_2", "tier_3"]
    preferred_source: bool
    age_hours: float | None
    topic: str | None
    provider: str | None
    summary: str | None
    why_it_matters: str | None
    citations: list[str]
    official_source: bool
```

### 캐시 파일 구조

```json
{
  "_meta": {
    "cached_at": "2026-04-04T08:00:00+00:00"
  },
  "btc_usd": { ...MarketPoint fields... },
  "us10y":   { ...MarketPoint fields... }
}
```

### `assess_data_quality` 반환값 추가 필드

```python
{
    # 기존 필드 (변경 없음)
    "status": "ok" | "degraded" | "critical",
    "zero_price_ratio": float,   # 기존 키 유지 (카테고리 최댓값으로 계산 방식 변경)
    ...
    # 신규 필드
    "zero_ratio_by_category": {
        "macro": float,
        "indices": float,
        "tech": float,
        "bitcoin": float,
    },
}
```

---

## Correctness Properties

*R1 (Provider 상수 단일화)*
- For any file in `src/morning_brief/data/` that uses a provider string, the value SHALL be imported from `providers.py` and no local definition of the same string SHALL exist.

*R2 (TypedDict)*
- For any `item` returned by `news_items_to_packet`, `item["age_hours"]` SHALL be `float | None` and mypy strict SHALL not report an error on typed access.

*R3 (캐시 TTL)*
- For any cache file saved by `_save_market_point_cache`, the JSON root SHALL contain `"_meta"` with `"cached_at"` as a valid ISO 8601 string.
- For any cache file where `cached_at` age > `max_age_hours`, `_load_market_point_cache` SHALL emit exactly one `WARNING` log with `event="cache.stale"`.

*R4 (카테고리별 zero_ratio)*
- For any `packet` with all macro prices missing and all tech prices present, `_zero_ratio_by_category(packet)["macro"]` SHALL be `1.0` and `["tech"]` SHALL be `0.0`.
- For any `packet`, `_zero_ratio(packet)` SHALL equal `max(_zero_ratio_by_category(packet).values())`.

*R5 (제목 dedup)*
- For any two `NewsItem` with identical `title[:40]` (normalized) but different URLs, `_dedup_and_rank` SHALL return at most one of them.
- For any two `NewsItem` with different `title[:40]` but identical URLs, the existing URL dedup behavior SHALL continue.

*R6 (XSignal dedup)*
- For any two `XSignal` with identical `source_handle` and identical `headline[:30]`, `_dedup_x_signals` SHALL return exactly one, retaining the one with the more recent `posted_at`.

*R7 (다국어 interpretation)*
- For any `NewsItem` with `why_it_matters = "N/A"`, `_has_meaningful_public_interpretation` SHALL return `False`.
- For any `NewsItem` with `why_it_matters = "The Fed raised rates by 25bps"`, the function SHALL return `True`.

*R8 (도메인 정책 YAML)*
- For any run where `config/domain_policy.yaml` exists and is valid, `domain_score("reuters.com")` SHALL return the same value as the YAML-defined score.
- For any run where `config/domain_policy.yaml` is missing OR has a schema error, the system SHALL emit a `WARNING` log and `domain_score("reuters.com")` SHALL return `5.0` (하드코딩 fallback). The pipeline SHALL NOT raise an exception or stop.
- For any call to `_resolve_domain_policy_path()`, the returned `Path` SHALL be absolute and SHALL NOT depend on the current working directory.

---

## Error Handling

| 상황 | 처리 방식 |
|------|---------|
| 캐시 파일 `_meta.cached_at` 파싱 실패 | 예외 무시, staleness 판정 skip, 기존대로 로드 |
| 캐시 파일이 stale (`age > max_age_hours`) | WARNING 로그(`event="cache.stale"`) 후 정상 로드 (중단 없음) |
| `fetch_newsletter_display_data` 경로에서 stale | 기본값 `max_age_hours=26`으로 동일하게 WARNING → 로드. settings 주입 없음 (이번 범위 밖) |
| `domain_policy.yaml` 미존재 | WARNING 로그(`event="config.fallback"`), 하드코딩 fallback 사용 |
| `domain_policy.yaml` 스키마 오류 / 파싱 실패 | WARNING 로그 + 하드코딩 fallback 사용 (파이프라인 중단 없음) |
| `providers.py`가 내부 모듈 임포트 시도 | 순환 임포트 → `ImportError`. `providers.py`는 stdlib/typing 전용. |
| `_dedup_x_signals` 빈 입력 | 빈 리스트 반환, 예외 없음 |
| TypedDict 키 없음 (런타임) | 일반 dict와 동일 동작 (`KeyError`), 기존 `.get()` 접근은 영향 없음 |
| `_zero_ratio_by_category` 카테고리 포인트 없음 | 해당 카테고리 `0.0` 반환 (분모 0 방지) |
| `_title_dedup_key` 제목 10자 미만 | 빈 문자열 반환 → 보조 dedup 비활성화, URL dedup만 적용 |

---

## Testing Strategy

**테스트 파일 위치:** `tests/` (기존 구조 유지)

### R1 (providers.py)
- `tests/test_providers.py` (신규): 모든 상수 값이 각 소스 파일에서 실제로 사용되는 값과 일치함을 검증. `grok_x_keyword.py`의 `NewsItem.provider` 설정 값이 `providers.GROK_X_KEYWORD`와 동일함을 확인.
- `providers.py` 자체가 내부 모듈을 임포트하지 않음을 `import providers` 단독 실행으로 검증 (ImportError 없음).

### R2 (TypedDict)
- `tests/test_news_packet.py` (신규 또는 확장): `news_items_to_packet` 반환값이 `NewsPacketItem` 스키마의 모든 키를 포함함을 검증.
- `pyproject.toml`의 mypy `files`에 `news_packet.py`, `providers.py` 추가 → `make typecheck`로 TypedDict 키 접근 타입 검증. **이 변경이 없으면 R2의 정적 분석 목적이 달성되지 않는다.**

### R3 (캐시 TTL)
- `tests/test_market_reliability.py` 확장:
  - `_meta.cached_at`이 저장된 파일을 로드 시 stale 판정 및 WARNING 로그 발생 검증
  - `cached_at` 없는 기존 포맷 캐시 파일이 경고 없이 정상 로드됨 검증

### R4 (카테고리별 zero_ratio)
- `tests/test_pipeline_quality.py` 확장:
  - macro 전부 누락 + indices 정상인 패킷에서 `zero_ratio_by_category["macro"] == 1.0` 검증
  - `zero_price_ratio == max(zero_ratio_by_category.values())` 검증
  - `assess_data_quality` 반환값에 `"zero_ratio_by_category"` 키 존재 검증

### R5 (제목 dedup)
- `tests/test_news_quality.py` 확장:
  - 동일 제목 앞 40자 + 다른 URL 2개 입력 시 1개만 반환 검증
  - 점수 높은 아이템이 유지됨 검증
  - 기존 URL dedup 케이스가 여전히 동작함 검증 (회귀)

### R6 (XSignal dedup)
- `tests/test_grok_x_keyword.py` 확장:
  - 동일 handle + headline[:30] XSignal 2개 입력 시 `posted_at` 최신 것 1개 반환
  - 빈 입력 → 빈 출력 검증

### R7 (다국어 interpretation)
- `tests/test_news_quality.py` 확장:
  - `"N/A"`, `"none"`, `"no information"` → `False`
  - `"The Fed raised rates by 25bps"` → `True`
  - 기존 한국어 패턴 ("없음", "해당없음") → `False` (회귀)

### R8 (도메인 정책 YAML)
- `tests/test_config.py` 확장:
  - 유효한 YAML 로드 시 하드코딩과 동일한 결과 반환 검증
  - YAML 미존재 시 WARNING 로그 + fallback 동작 검증
  - 스키마 오류 YAML 시 WARNING 로그 + fallback 동작 검증 (ValueError 아님 — 오류 처리 정책 변경 반영)
  - `_resolve_domain_policy_path()`가 CWD 무관하게 동일 경로 반환함을 검증
