# Fallback 브리핑 데이터 기반 전환 구현 계획

> 작성일: 2026-03-17
> 범위: `src/morning_brief/briefing.py` 내 `_fallback_brief` 및 관련 헬퍼 함수
> 원칙: 모델/파이프라인 구조 변경 없음. 고정 문장 → 데이터 조건 분기로만 교체.

---

## 변경 대상 전수 조사

`_fallback_brief` 템플릿 안의 모든 텍스트를 "이미 동적" vs "고정(하드코딩)" 으로 분류했다.

### ✅ 이미 데이터 기반 (변경 불필요)

| 위치 | 함수/변수 | 동작 |
|------|----------|------|
| LAYER 1 한줄결론 | `_judgement_and_reason()` | VIX/NQ/SPY/환율 기반 매수관심/관망/리스크주의 분기 |
| LAYER 1 핵심수치 | `_korea_watch_lines()` | 환율/선물/공포탐욕 실제 값 출력 |
| LAYER 1 코스피영향 | `_kospi_impact_line()` | NQ/환율/SPY 기반 4방향 분기 |
| LAYER 2 핵심이슈 | `_fallback_news_lines()` | 실제 뉴스 title/why_it_matters 사용 |
| LAYER 3 주요지표 | `_fallback_stock_lines()` | 실제 종목 등락률 + 원인 추론 |
| LAYER 3 거시지표 | `_fallback_macro_lines()` | 실제 매크로 값 출력 |

### ❌ 고정 문장 (변경 필요) — 총 8곳

| # | 위치 | 현재 고정 문장 | 문제 |
|---|------|--------------|------|
| H1 | LAYER 1 "쉽게 보면" | "금리와 달러, 지수 흐름이 한 방향으로 정렬되지 않아..." | 정렬됐을 때도 동일 |
| H2 | LAYER 1 체크포인트 | "전일 종가 대비 금리와 기술주 반응이..." / "BTC ETF 자금 흐름이..." | 매일 동일 |
| H3 | LAYER 2 한줄결론 | "금리 경로, AI 투자 기대, 비트코인 ETF 수급처럼..." | 뉴스 토픽과 무관 |
| H4 | LAYER 2 왜중요한지 | H3과 동일 문장 + 고정 부연 | 복붙 + 매일 동일 |
| H5 | LAYER 2 체크포인트 | "같은 주제를 다른 신뢰 출처도..." / "공식 채널 확인이..." | 매일 동일 |
| H6 | LAYER 3 한줄결론 | "AI와 반도체 기대가 유지된 구간과, 금리 부담이..." | 하락장에서도 동일 |
| H7 | LAYER 3 쉽게보면 | "같은 AI 테마 안에서도 차이가 보였고..." + 부연 | 매일 동일 |
| H8 | LAYER 3 체크포인트 | "대형 기술주와 반도체의 등락률 차이가..." / "VIX, 달러..." | 매일 동일 |

### ⚠️ 부분 개선 (변경 권장) — 1곳

| # | 위치 | 현재 | 문제 |
|---|------|------|------|
| P1 | `_fallback_news_takeaway()` | 토픽별 4종 고정 문장 | 뉴스 내용 미반영 |

---

## 구현 계획

### Step 1: 방향성 시그널 수집 헬퍼 추가

`_fallback_brief`에서 공통으로 쓸 시장 방향성 요약 dict를 만든다.

```python
def _direction_signals(macro, indices, korea_watch, tech, btc_spot):
    """데이터에서 상승/하락/혼조/미확인 시그널을 수집한다."""
    # 반환: {"overall": "bullish"|"bearish"|"mixed"|"unknown",
    #        "vix": float|None, "nq_change": float|None, ...
    #        "top_gainer": str|None, "top_loser": str|None,
    #        "available_topics": set[str]}
```

이 dict를 H1~H8 전체에서 참조한다. 기존 `_judgement_and_reason`과 중복 계산을 피하기 위해 이미 계산된 값을 재사용한다.

**변경 파일**: `briefing.py`
**신규 함수**: `_direction_signals()`

### Step 2: H1 — LAYER 1 "쉽게 보면" 데이터 분기

```python
def _layer1_easy_summary(signals):
    if signals["overall"] == "bullish":
        return "금리가 안정되고 지수와 선물이 함께 강해, 위험자산 선호가 이어지는 흐름입니다."
    if signals["overall"] == "bearish":
        return "금리 부담과 지수 약세가 겹쳐, 방어적 시각이 우선되는 흐름입니다."
    if signals["overall"] == "mixed":
        return "금리와 지수 신호가 엇갈려, 한쪽 방향을 단정하기 어려운 구간입니다."
    return "주요 지표가 충분히 확인되지 않아, 장 마감 후 추가 확인이 필요합니다."
```

**변경 파일**: `briefing.py`
**신규 함수**: `_layer1_easy_summary()`
**템플릿 교체**: `_fallback_brief` 내 LAYER 1 "쉽게 보면" 고정 문장 → `{_layer1_easy_summary(signals)}`

### Step 3: H2, H5, H8 — 체크포인트 동적 생성

3개 LAYER의 체크포인트를 모두 데이터 기반으로 교체한다.

```python
def _dynamic_checkpoints(signals, layer: str) -> list[str]:
    """layer별로 당일 데이터에서 주목할 포인트 1~2개를 생성한다."""
    points = []
    if layer == "layer1":
        # VIX 높으면 변동성 체크, NQ 방향 강하면 본장 연속성 체크 등
    elif layer == "layer2":
        # 뉴스 토픽 기반: 수집된 토픽에 따라 후속 확인 포인트
    elif layer == "layer3":
        # 종목 등락 기반: 가장 큰 움직임 종목의 후속 체크
    if not points:
        points.append("장 마감 후 주요 지표 방향이 정리되는지")
    return points[:2]
```

**변경 파일**: `briefing.py`
**신규 함수**: `_dynamic_checkpoints()`
**템플릿 교체**: `_fallback_brief` 내 3곳의 고정 체크포인트 → `{_bullet_lines(_dynamic_checkpoints(signals, "layerN"))}`

### Step 4: H3, H4 — LAYER 2 한줄결론 + 왜중요한지

```python
TOPIC_LABEL = {"macro": "거시경제", "ai_bigtech": "AI·빅테크", "us_equity": "미국 증시", "bitcoin": "비트코인"}

def _layer2_headline(news):
    if not news:
        return "오늘은 주요 뉴스가 충분히 수집되지 않아 시장 해석을 보수적으로 유지합니다."
    topics = sorted({item.get("topic") for item in news if item.get("topic")})
    labels = [TOPIC_LABEL.get(t, t) for t in topics]
    return f"오늘 뉴스는 {', '.join(labels)} 쪽에 집중됐습니다."

def _layer2_why_matters(news):
    if len(news) < 2:
        return ""  # 뉴스 부족 시 블록 자체 생략
    # 뉴스 간 공통 토픽을 1문장으로 연결
    ...
```

**핵심**: 한줄결론 ≠ 왜중요한지. 복붙 제거.
**변경 파일**: `briefing.py`
**신규 함수**: `_layer2_headline()`, `_layer2_why_matters()`

### Step 5: H6, H7 — LAYER 3 한줄결론 + 쉽게보면

```python
def _layer3_headline(tech, btc_spot_change):
    gainers = [p for p in tech if (_point_change_pct(p) or 0) > 0.1]
    losers = [p for p in tech if (_point_change_pct(p) or 0) < -0.1]
    if gainers and losers:
        return f"오늘은 {gainers[0]['label']} 등이 강했고 {losers[0]['label']} 등은 약했습니다."
    if gainers:
        return f"기술주 전반이 상승했고, {gainers[0]['label']}의 상승폭이 가장 컸습니다."
    if losers:
        return f"기술주 전반이 약했고, {losers[0]['label']}의 하락폭이 가장 컸습니다."
    return "주요 종목 등락률이 충분히 확인되지 않았습니다."

def _layer3_easy_summary(signals):
    if signals["overall"] == "bullish":
        return "기술주와 비트코인이 함께 강해, 위험자산 전반에 자금이 들어오는 흐름으로 읽힙니다."
    if signals["overall"] == "bearish":
        return "기술주와 비트코인이 함께 약해, 위험자산에서 자금이 빠지는 흐름으로 읽힙니다."
    # mixed / unknown 분기
    ...
```

**변경 파일**: `briefing.py`
**신규 함수**: `_layer3_headline()`, `_layer3_easy_summary()`

### Step 6: P1 — 뉴스 takeaway 개선

```python
def _fallback_news_takeaway(item):
    wim = str(item.get("why_it_matters", "")).strip()
    if wim:
        return f"국내 투자자에게는 {wim}와 국내 관련주 반응을 함께 볼 필요가 있습니다."
    # 기존 토픽 기반 기본값 유지 (최후방)
    topic = str(item.get("topic", "")).strip().lower()
    ...
```

**변경 파일**: `briefing.py`
**기존 함수 수정**: `_fallback_news_takeaway()`

### Step 7: 뉴스 0건 시 LAYER 2 축소

뉴스가 0건이면 "핵심 이슈 / 왜 중요한지 / 체크포인트" 전체를 한 블록으로 축소한다.

```
2. LAYER 2 | 주요 뉴스
한줄 결론
오늘은 주요 뉴스가 충분히 수집되지 않았습니다. 장중 주요 매체를 직접 확인하는 편이 적절합니다.

핵심 이슈
- 수집된 뉴스가 없어 시장 해석을 보수적으로 유지합니다. | 장중 Reuters, Bloomberg 등 주요 매체를 직접 확인하는 편이 적절합니다. | 국내 투자자에게는 환율과 선물 흐름으로 방향을 가늠할 필요가 있습니다. | 출처 없음
```

**변경 파일**: `briefing.py`
**기존 함수 수정**: `_fallback_brief()` 내 LAYER 2 블록

---

## 변경하지 않는 것

- `_judgement_and_reason()` — 이미 데이터 기반 분기 완료
- `_kospi_impact_line()` — 이미 4방향 분기 완료
- `_korea_watch_lines()` — 이미 실제 값 출력
- `_fallback_stock_lines()` / `_fallback_stock_cause()` — 이미 데이터 기반
- `_fallback_macro_lines()` — 이미 실제 값 출력
- `_brief_structure_issues()` — 검증 로직 유지
- 프롬프트 템플릿 (`prompts/*.j2`) — 변경 없음
- 파이프라인 / 모델 / 수집 로직 — 변경 없음

---

## 구현 순서 및 예상 영향

| Step | 대상 | 신규 함수 | 수정 함수 | 테스트 영향 |
|------|------|----------|----------|------------|
| 1 | 시그널 수집 | `_direction_signals` | — | 없음 (내부 헬퍼) |
| 2 | LAYER 1 쉽게보면 | `_layer1_easy_summary` | `_fallback_brief` | 기존 테스트 문자열 매칭 변경 가능 |
| 3 | 체크포인트 3곳 | `_dynamic_checkpoints` | `_fallback_brief` | 기존 테스트 문자열 매칭 변경 가능 |
| 4 | LAYER 2 한줄결론/왜중요한지 | `_layer2_headline`, `_layer2_why_matters` | `_fallback_brief` | 기존 테스트 문자열 매칭 변경 가능 |
| 5 | LAYER 3 한줄결론/쉽게보면 | `_layer3_headline`, `_layer3_easy_summary` | `_fallback_brief` | 기존 테스트 문자열 매칭 변경 가능 |
| 6 | 뉴스 takeaway | — | `_fallback_news_takeaway` | 기존 테스트 문자열 매칭 변경 가능 |
| 7 | 뉴스 0건 축소 | — | `_fallback_brief` | 구조 검증 테스트 확인 필요 |

---

## 검증 계획

1. `ruff format --check` + `ruff check` 통과
2. `pytest -q` 전체 통과 (문자열 매칭 테스트는 함께 수정)
3. 수동 검증: 아래 3가지 시나리오에서 fallback 출력 확인
   - 전체 데이터 정상 + OpenAI 구조 실패 → fallback 발동
   - 부분 데이터 (매크로만 성공, 뉴스 0건) → LAYER 2 축소 확인
   - 전체 데이터 missing → "확인되지 않았습니다" 계열 출력 확인
4. 연속 2회 다른 데이터로 실행 시 고정 문장이 반복되지 않는지 확인

---

## 리뷰 결과 (2026-03-17)

### ✅ 계획 유효성 확인

1. **변경 대상 8+1곳 정확함** — `_fallback_brief` 템플릿 안의 고정 문장만 교체하면 되고, 이미 데이터 기반인 6개 함수는 건드릴 필요 없음 확인.
2. **구조 검증 호환성 확인** — `_brief_structure_issues()`는 3개 LAYER 헤딩 존재 + LAYER 2 bullet ≥ 2 + LAYER 3 bullet ≥ 2만 검사함. 고정 문장을 교체해도 이 구조만 유지하면 통과.
3. **뉴스 0건 축소(Step 7)도 안전** — LAYER 2에 최소 2개 bullet이 필요하므로, 축소 시에도 `핵심 이슈` 아래 dummy bullet 2개는 유지해야 함. 계획에 반영 필요.

### ⚠️ 수정/보완 필요 사항

| # | 항목 | 내용 |
|---|------|------|
| R1 | **Step 7 뉴스 0건 축소 시 bullet 최소 2개 유지** | `_brief_structure_issues`가 LAYER 2 bullet ≥ 2를 검사하므로, 뉴스 0건이어도 `핵심 이슈` 아래 2줄 이상 유지해야 함. 계획의 "한 블록 축소"를 "핵심 이슈 2줄 유지 + 왜중요한지/체크포인트 생략"으로 수정. |
| R2 | **Step 1 `_direction_signals` 과설계 주의** | `_judgement_and_reason()`이 이미 VIX/NQ/SPY/환율 기반 분기를 하고 있음. 새 함수가 같은 계산을 반복하면 유지보수 부담. → `_judgement_and_reason`의 반환값을 확장하거나, 최소한의 `overall` 방향만 추출하는 경량 함수로 제한. |
| R3 | **테스트 영향 범위 한정** | 고정 문장을 직접 assert하는 테스트는 없음 확인. 영향받는 테스트: `test_fallback_brief_mentions_official_btc_etf_flow_when_available` (LAYER 헤딩 존재 + BTC ETF 문자열 확인), `test_fallback_brief_marks_previous_values_and_appends_footer_notes` (전일값 표시 확인), `test_fallback_brief_includes_korean_investor_signals` (매수관심/환율/선물/공포탐욕 문자열 확인). 이 3개 테스트는 구조와 데이터 값을 검증하므로 고정 문장 교체와 무관하게 통과해야 함. |
| R4 | **`_fallback_news_takeaway` 개선 시 문장 자연스러움** | `why_it_matters`를 그대로 이어붙이면 "국내 투자자에게는 AI 투자 기대와 국내 관련주 반응을 함께 볼 필요가 있습니다" 같은 어색한 문장이 나올 수 있음. `why_it_matters`가 있으면 그것만 단독 사용하고, 없을 때만 토픽 기본값 사용하는 방식이 더 자연스러움. |

### 수정된 Step 7

뉴스 0건 시 LAYER 2:
```
2. LAYER 2 | 주요 뉴스
한줄 결론
오늘은 주요 뉴스가 충분히 수집되지 않았습니다. 장중 주요 매체를 직접 확인하는 편이 적절합니다.

핵심 이슈
- 수집된 뉴스가 없어 시장 해석을 보수적으로 유지합니다. | 장중 Reuters, Bloomberg 등을 직접 확인하는 편이 적절합니다. | 국내 투자자에게는 환율과 선물 흐름으로 방향을 가늠할 필요가 있습니다.
- 뉴스 부재 시에는 지표 흐름과 전일 대비 변화율 중심으로 판단하는 편이 적절합니다. | 가격 데이터만으로도 방향성 확인은 가능합니다. | 국내 투자자에게는 원/달러 환율과 나스닥 선물 방향을 우선 확인할 필요가 있습니다.
```

### 수정된 Step 1

`_direction_signals()`를 별도 함수로 만들되, `_judgement_and_reason()`과 계산을 공유하지 않고 **judgement 결과를 입력으로 받아 overall만 매핑**하는 경량 함수로 제한:

```python
def _overall_direction(judgement: str) -> str:
    if judgement == "매수 관심":
        return "bullish"
    if judgement == "리스크 주의":
        return "bearish"
    return "mixed"
```

### 수정된 Step 6

```python
def _fallback_news_takeaway(item):
    wim = str(item.get("why_it_matters", "")).strip()
    if wim:
        return wim  # why_it_matters 단독 사용
    # 기존 토픽 기반 기본값 유지
    ...
```

### 최종 구현 순서

1. `_overall_direction()` 추가 (경량, judgement 결과 매핑만)
2. LAYER 1 "쉽게 보면" 교체 (H1)
3. LAYER 2 한줄결론 교체 (H3) + 왜중요한지 교체 (H4) + 뉴스 0건 축소 (Step 7)
4. LAYER 3 한줄결론 (H6) + 쉽게보면 (H7) 교체
5. 체크포인트 3곳 동적 생성 (H2, H5, H8)
6. `_fallback_news_takeaway` 개선 (P1)
7. `ruff format` + `ruff check` + `pytest -q`
