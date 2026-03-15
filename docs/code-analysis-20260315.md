# Morning Market Brief 코드 분석 (2026-03-15)

## 1. 구조적 문제

### 1-1. `market.py` God Module (32KB, ~600줄)

시장 데이터 수집, 캐시 관리, 이상값 검증, BTC ETF 요약까지 하나의 파일에 몰려 있습니다.

```python
# market.py에 혼재된 책임들:
def fetch_macro_points(...)          # 거시지표 수집
def fetch_us_index_points(...)       # 미국 지수 수집
def fetch_tech_stock_points(...)     # 기술주 수집
def fetch_bitcoin_snapshot(...)      # BTC 전체 스냅샷
def _load_market_point_cache(...)    # 캐시 로드
def _save_market_point_cache(...)    # 캐시 저장
def _validate_market_point(...)      # 이상값 검증
def _resolve_point_from_cache(...)   # 캐시 폴백 해소
def _summarize_official_btc_etf_snapshots(...)  # ETF 요약 계산
def build_market_packet(...)         # 전체 오케스트레이션
```

캐시 I/O, 검증 로직, ETF 요약 계산은 별도 모듈로 분리하는 것이 유지보수에 유리합니다.

### 1-2. `briefing.py` 이중 역할 (27KB, ~740줄)

OpenAI 호출 + fallback 브리핑 생성 + 구조 검증 + 참조 블록 조립이 한 파일에 있습니다.

```python
# briefing.py 안에 ~400줄짜리 fallback 브리핑 템플릿이 Python 문자열로 존재
def _fallback_brief(packet: dict, timezone: str) -> str:
    # ... f-string으로 전체 브리핑 본문을 조립
    body = f"""미국 기술주·비트코인 시장 브리핑 ({now.strftime('%Y-%m-%d')})
{quality_notice}
1. LAYER 1 | 오늘 한줄 판단
...
"""
```

이 fallback 브리핑은 Jinja 템플릿으로 관리되는 메인 프롬프트와 달리 Python 코드 안에 하드코딩되어 있어, 내용 수정 시 코드 변경이 필요합니다.

### 1-3. `emailer.py` 과도한 크기 (32KB)

HTML 렌더링, 톤 분석, 섹션 파싱, Gmail OAuth, MIME 조립이 전부 한 파일입니다.

```python
# emailer.py에 정의된 데이터 클래스만 5개
@dataclass(frozen=True)
class _EmailSection: ...
class _EmailNewsItem: ...
class _EmailBriefRow: ...
class _EmailSourceItem: ...
# + GmailSender 클래스 + 수십 개의 private 헬퍼 함수
```

---

## 2. 데이터 흐름 문제

### 2-1. dict 기반 패킷 전달 — 타입 안전성 부재

파이프라인 전체에서 `dict`를 주고받으며, 키 이름이 문자열 상수로만 관리됩니다.

```python
# pipeline.py
packet = {
    **market_packet,       # dict
    "news": news_packet,   # list[dict]
}
packet["data_quality"] = quality  # dict

# briefing.py에서 접근할 때
def _point_price(point: dict) -> float | None:
    resolved = point.get("resolved_value")  # 키 오타 시 None 반환, 에러 없음
    ...
```

`MarketPoint`는 dataclass로 정의되어 있지만, `build_market_packet()`에서 `__dict__`로 변환한 뒤 이후 모든 소비자가 `dict`로 접근합니다:

```python
# market.py:build_market_packet()
packet = {
    "macro": [point.__dict__ for point in macro_points],  # dataclass → dict 변환
    "tech_stocks": [point.__dict__ for point in tech_stock_points],
    ...
}
```

### 2-2. 모듈 간 순환 의존 위험

`news.py`가 `data_quality.py`의 함수를 직접 import하고, `news_selection.py`도 `data_quality.py`를 호출합니다:

```python
# news.py
from morning_brief.data.data_quality import assess_perplexity_fallback_need

# news_selection.py
def _packet_summary(items):
    from morning_brief.data.data_quality import summarize_news_packet_quality  # 지연 import
```

`_packet_summary` 안의 지연 import는 순환 참조를 피하기 위한 것으로 보이지만, 구조적 의존 방향이 정리되지 않은 신호입니다.

---

## 3. 에러 처리 / 복원력 문제

### 3-1. `_warn_once` 전역 상태 누수

```python
# market.py
_provider_warned: set[str] = set()

def _warn_once(key: str, message: str, *args) -> None:
    if key in _provider_warned:
        return
    _provider_warned.add(key)
    logger.warning(message, *args)
```

모듈 레벨 `set`이므로 프로세스가 살아 있는 동안 계속 누적됩니다. `reset_provider_runtime_state()`가 `provider_runtime.py`의 상태만 초기화하고, `market.py`의 `_provider_warned`는 리셋하지 않습니다. 스케줄러 모드(`main.py schedule`)에서 매일 반복 실행 시 두 번째 실행부터 경고가 누락될 수 있습니다.

### 3-2. BTC ETF 스냅샷 stale 캐시 무한 재사용

```python
# market.py:_fetch_official_btc_etf_data()
if not snapshots:
    if previous_snapshots:
        # 새 스냅샷 실패 시 이전 캐시를 그대로 반환
        return (
            previous_snapshots,
            *_summarize_official_btc_etf_snapshots(
                snapshots=previous_snapshots,
                previous_by_ticker={},  # 비교 대상 없음 → flow 계산 불가
                spot_price_usd=spot_price_usd,
            ),
        )
```

Perplexity가 며칠간 실패하면 오래된 캐시가 계속 사용되지만, 캐시 나이(staleness)를 확인하는 로직이 없습니다. 며칠 전 데이터가 "현재 보유량"으로 브리핑에 들어갈 수 있습니다.

### 3-3. pipeline.py의 `BriefGenerationError` 외 예외 재발생

```python
# pipeline.py
except Exception as exc:
    status = "failed"
    failure_message = str(exc)
    failure_exc = exc
    observer.log_event("pipeline_error", reason=failure_message)
    raise  # ← finally 블록 실행 후 재발생
...
finally:
    ...
if failure_exc is not None:
    raise failure_exc  # ← 이미 위에서 raise 했는데 여기서 또 raise
```

`BriefGenerationError`가 아닌 일반 `Exception`의 경우, `except` 블록에서 `raise`로 즉시 재발생하고, `finally` 이후 `raise failure_exc`도 실행됩니다. `except` 블록의 `raise`가 `finally`를 거쳐 전파되므로 `raise failure_exc`는 `BriefGenerationError` 경우에만 실질적으로 동작합니다. 의도는 맞지만 흐름이 혼란스럽습니다.

---

## 4. 설정 / 환경 문제

### 4-1. README와 코드의 기본값 불일치

README에는 `OPENAI_MAX_OUTPUT_TOKENS` 기본값이 `1700`으로 문서화되어 있지만, 코드에서는 `2300`입니다:

```python
# config.py
openai_max_output_tokens=_env_bounded_int(
    "OPENAI_MAX_OUTPUT_TOKENS",
    default=2300,   # ← README에는 1700
    minimum=500,
    maximum=4000,
),
```

### 4-2. 사용하지 않는 설정이 여전히 로드됨

README에 "하위 호환용으로만 남아 있고 현재 파이프라인에서는 사용하지 않습니다"라고 명시된 `OPENAI_WEB_SEARCH_*` 환경변수가 `Settings`에 여전히 존재하고 `load_settings()`에서 로드됩니다:

```python
# config.py:Settings
openai_web_search_enabled: bool
openai_web_search_model: str
openai_web_search_max_results: int
```

그런데 `pipeline.py`에서는 실제로 `settings.openai_web_search_enabled`를 사용하고 있어, "사용하지 않는다"는 README 설명과 모순됩니다:

```python
# pipeline.py
if not settings.openai_web_search_enabled:
    observer.log_event("backfill_skipped", ...)
```

---

## 5. 뉴스 수집 로직 문제

### 5-1. `news.py`의 과도한 re-export

```python
# news.py — 모듈 상단에서 내부 헬퍼를 re-export
_dedup_and_rank = news_selection._dedup_and_rank
_domain_score = news_policy.domain_score
_extract_domain = news_policy.extract_domain
_is_preferred_domain = news_policy.is_preferred_domain
_item_score = news_selection._item_score
_merge_rank = news_selection._merge_rank
_normalize_url = news_selection._normalize_url
_packet_summary = news_selection._packet_summary
_provider_breakdown = news_selection._provider_breakdown
_provider_counts = news_selection._provider_counts
summarize_news_packet_quality = data_quality.summarize_news_packet_quality
```

`_` prefix 함수(private 의도)를 다른 모듈에서 직접 참조하고, 이를 다시 re-export합니다. 테스트에서 `news.py`를 통해 접근하는 패턴이 고착되면 리팩터링이 어려워집니다.

### 5-2. Perplexity fallback 판단 기준의 분산

Perplexity 결과 품질 판단이 `data_quality.py`의 `assess_perplexity_fallback_need()`와 `news.py`의 `_needs_full_legacy_backfill()`로 나뉘어 있습니다:

```python
# data_quality.py
def assess_perplexity_fallback_need(news_packet):
    summary = summarize_news_packet_quality(news_packet)
    reasons = _build_perplexity_fallback_reasons(summary)
    return {"needs_legacy_fallback": bool(reasons), "reasons": reasons, ...}

# news.py
def _needs_full_legacy_backfill(fallback_review: dict) -> bool:
    return any([
        int(fallback_review.get("count", 0)) == 0,
        int(fallback_review.get("fresh_count", 0)) == 0,
        int(fallback_review.get("unique_domains", 0)) < 2,
        int(fallback_review.get("citation_backed_count", 0)) == 0,
    ])
```

"legacy fallback이 필요한가"와 "full backfill이 필요한가"의 기준이 서로 다른 모듈에 있어, 임계값 조정 시 양쪽을 모두 확인해야 합니다.

---

## 6. 성능 / 효율 문제

### 6-1. 시장 데이터 순차 수집

`build_market_packet()`에서 모든 수집이 순차적으로 실행됩니다:

```python
# market.py:build_market_packet()
macro_points = fetch_macro_points(fred_api_key=fred_api_key)       # FRED + yfinance
korea_watch_points = fetch_korea_investor_points()                  # yfinance
us_index_points = fetch_us_index_points()                           # Stooq + yfinance
tech_stock_points = fetch_tech_stock_points()                       # Stooq + yfinance (10종)
btc_snapshot = fetch_bitcoin_snapshot(...)                          # CoinGecko + Stooq + Perplexity
```

provider별 rate limit이 있지만, 서로 다른 provider 간 요청은 병렬화 가능합니다. 현재는 FRED → yfinance → Stooq → CoinGecko → Perplexity 순서로 직렬 실행되어 전체 수집 시간이 길어집니다.

### 6-2. yfinance 반복 호출

`_safe_stooq_point_and_volume()`에서 Stooq 실패 시 yfinance fallback이 가격과 거래량을 별도 호출합니다:

```python
# market.py
fallback_fetch=lambda: (
    _safe_yfinance_point(label=label, ticker=ticker, ...),  # period="5d"
    _volume_from_yfinance(ticker=ticker),                    # period="2d"
),
```

같은 ticker에 대해 yfinance를 두 번 호출합니다. `_history_with_retry`가 한 번 호출되면 가격과 거래량을 동시에 추출할 수 있습니다.

---

## 7. 테스트 / 품질 문제

### 7-1. `perplexity_search.py` 테스트 파일 크기 (50KB)

`tests/test_perplexity_search.py`가 50KB로, 소스 파일(39KB)보다 큽니다. 테스트 fixture와 mock 데이터가 과도하게 인라인되어 있을 가능성이 높습니다.

### 7-2. `conftest.py`가 최소한

```python
# tests/conftest.py — 450바이트
```

공통 fixture가 거의 없어 각 테스트 파일이 독립적으로 mock을 구성하고 있을 것으로 보입니다. 반복되는 패턴(예: Settings mock, observer mock)이 있다면 conftest로 추출하는 것이 좋습니다.

---

## 8. 요약 — 우선순위별 개선 제안

| 우선순위 | 문제 | 영향 | 제안 |
|---------|------|------|------|
| 높음 | dict 기반 패킷 전달 | 키 오타 시 런타임 에러 없이 None 전파 | TypedDict 또는 dataclass 패킷 도입 |
| 높음 | README ↔ 코드 기본값 불일치 | 운영자 혼란 | README 동기화 |
| 높음 | `_warn_once` 상태 미초기화 | 스케줄러 모드에서 경고 누락 | `reset_provider_runtime_state()`에서 함께 초기화 |
| 높음 | BTC ETF stale 캐시 무한 재사용 | 오래된 데이터가 현재 값으로 표시 | 캐시 TTL 또는 staleness 경고 추가 |
| 중간 | `market.py` 분리 | 변경 시 영향 범위 파악 어려움 | 캐시/검증/ETF 요약을 별도 모듈로 |
| 중간 | fallback 브리핑 하드코딩 | 내용 수정 시 코드 변경 필요 | Jinja 템플릿으로 이관 |
| 중간 | 순차 수집 | 파이프라인 실행 시간 증가 | provider별 병렬 수집 검토 |
| 낮음 | `news.py` private 함수 re-export | 리팩터링 저항 | 테스트가 원본 모듈을 직접 import하도록 변경 |
| 낮음 | yfinance 이중 호출 | 불필요한 API 호출 | 한 번 호출로 가격+거래량 추출 |
