# Grok API 비용 추적 개선

> 파이프라인이 보고하는 비용과 xAI 대시보드 실제 과금 사이에 ~5배 차이가 발생합니다.

---

## 현상

| 항목 | 파이프라인 기록 | xAI 대시보드 |
|---|---|---|
| 토큰 비용 | $0.017 | $0.013 |
| X search 호출 비용 | **$0 (미추적)** | **$0.06** |
| 합계 | $0.017 | **$0.073** |

비용의 **82%가 X search tool invocation fee**이고 파이프라인이 이를 전혀 추적하지 못합니다.

---

## 원인 분석 (코드 기반)

### 1. X search tool invocation 비용이 비용 모델에 없음

`observability.py`의 `LLM_PRICING_USD_PER_1M`은 **토큰 단가만** 정의합니다:

```python
"grok_official": {
    "input": 0.200,
    "output": 0.500,
    "cached_input": 0.050,
    "reasoning": None,
}
```

xAI 공식 요금표에 따르면 X search는 **$5 / 1,000 calls = $0.005 per call**로 토큰과 별도 과금됩니다. 이 비용이 `_provider_cost_usd`에 반영되지 않습니다.

### 2. 모델이 자율적으로 x_search를 여러 번 호출

파이프라인이 Grok API를 4~5회 호출하지만, 각 호출 안에서 모델이 agent로서 `x_search` tool을 **자율적으로 여러 번** 호출합니다. xAI 대시보드에 $0.06이 찍혔다면 약 12회 x_search 호출 ($0.06 / $0.005).

### 3. `_usage_snapshot`이 tool call 횟수를 파싱하지 않음

```python
# grok_official_signals.py:81-98
def _usage_snapshot(response: object) -> dict[str, int | None]:
    usage = _usage_field(response, "usage")
    return {
        "input_tokens": ...,
        "output_tokens": ...,
        "cached_input_tokens": ...,
        "reasoning_tokens": ...,
        # x_search_calls → 없음
    }
```

### 4. `grok_web_search`가 비용 모델에 아예 없음

`LLM_PRICING_USD_PER_1M`에 `grok_web_search` 키가 없어서 web search 호출의 토큰 비용도 $0으로 보고됩니다.

### 5. `ProviderUsageTotals`에 tool invocation 필드 없음

```python
# observability.py:70-78
class ProviderUsageTotals:
    requests: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    # x_search_calls → 없음
    # web_search_calls → 없음
```

---

## 수정 방안

### 핵심: `cost_in_usd_ticks` 필드 활용 (xAI 공식 문서 기반)

xAI API 응답의 `usage` 객체에 **이미 정확한 총 비용이 포함**되어 있습니다:

```json
"usage": {
    "prompt_tokens": 199,
    "completion_tokens": 1,
    "total_tokens": 200,
    "num_sources_used": 0,
    "cost_in_usd_ticks": 158500
}
```

- `cost_in_usd_ticks`: 토큰 비용 + tool invocation 비용(X search, web search 등) **모두 포함**된 총 비용
- 단위: 1/10,000,000,000 USD (= 10^-10 달러)
- 변환: `cost_usd = cost_in_usd_ticks / 10_000_000_000`
- `num_sources_used`: 검색에 사용된 소스 수 (X search call 횟수 추정에 활용 가능)

**현재 파이프라인의 `_usage_snapshot`은 이 두 필드를 모두 무시합니다.**

### A. `_usage_snapshot`에 `cost_in_usd_ticks`와 `num_sources_used` 추가

```python
def _usage_snapshot(response: object) -> dict[str, int | None]:
    usage = _usage_field(response, "usage")
    return {
        "input_tokens": _usage_int(usage, "prompt_tokens"),
        "output_tokens": _usage_int(usage, "completion_tokens"),
        "cached_input_tokens": _first_usage_int(
            usage,
            ("cached_prompt_text_tokens",),
            ("prompt_tokens_details", "cached_tokens"),
            ("input_tokens_details", "cached_tokens"),
        ),
        "reasoning_tokens": _first_usage_int(
            usage,
            ("completion_tokens_details", "reasoning_tokens"),
            ("output_tokens_details", "reasoning_tokens"),
            ("reasoning_tokens",),
        ),
        "cost_in_usd_ticks": _usage_int(usage, "cost_in_usd_ticks"),  # ← 추가
        "num_sources_used": _usage_int(usage, "num_sources_used"),     # ← 추가
    }
```

### B. `_provider_cost_usd`에서 `cost_in_usd_ticks` 우선 사용

xAI provider인 경우 토큰 단가 계산 대신 API가 알려주는 정확한 비용을 사용:

```python
def _provider_cost_usd(..., cost_in_usd_ticks: int | None = None) -> float | None:
    # xAI가 정확한 비용을 알려주면 그걸 쓴다
    if cost_in_usd_ticks is not None:
        return round(cost_in_usd_ticks / 10_000_000_000, 6)
    # 그 외 provider는 기존 토큰 단가 계산
    ...
```

### C. `ProviderUsageTotals`에 필드 추가

```python
class ProviderUsageTotals:
    requests: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost_in_usd_ticks: int | None = None   # ← 추가
    num_sources_used: int = 0              # ← 추가
```

### D. `LLM_PRICING_USD_PER_1M`에 `grok_web_search` 추가

`cost_in_usd_ticks`가 없는 경우의 폴백용:

```python
"grok_web_search": {
    "input": 0.200,
    "output": 0.500,
    "cached_input": 0.050,
    "reasoning": None,
},
```

---

## 수정 대상 파일

| 파일 | 변경 |
|---|---|
| `observability.py` | `ProviderUsageTotals`에 `cost_in_usd_ticks`, `num_sources_used` 추가 |
| `observability.py` | `_provider_cost_usd`에서 `cost_in_usd_ticks` 우선 사용 로직 추가 |
| `observability.py` | `LLM_PRICING_USD_PER_1M`에 `grok_web_search` 추가 (폴백용) |
| `grok_official_signals.py` | `_usage_snapshot`에 `cost_in_usd_ticks`, `num_sources_used` 파싱 추가 |
| `grok_x_keyword.py` | 동일 |
| `grok_web_search.py` | 동일 |
| 관련 테스트 | `cost_in_usd_ticks` 기반 비용이 xAI 대시보드와 일치하는지 검증 |

---

## 기대 효과

수정 전 (토큰 단가 직접 계산):
```
grok_official:  $0.008944  (토큰만)
grok_keyword:   $0.008407  (토큰만)
합계:           $0.017     ← xAI 대시보드 $0.073과 5배 차이
```

수정 후 (`cost_in_usd_ticks` 사용):
```
grok_official:  $0.039  (토큰 + X search fee 포함)
grok_keyword:   $0.034  (토큰 + X search fee 포함)
합계:           $0.073  ← xAI 대시보드와 일치
```
