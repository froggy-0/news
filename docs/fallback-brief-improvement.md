# Fallback 브리핑 품질 개선 리서치 & 설계

> 작성일: 2026-03-17
> 목적: `_fallback_brief` 하드코딩 문장을 데이터 기반 동적 생성으로 교체

---

## 1. 현재 문제 진단

### 1.1 하드코딩 문장 목록

현재 `briefing.py`의 `_fallback_brief`에는 데이터와 무관하게 매일 동일한 문장이 출력되는 구간이 있다.

| 위치 | 고정 문장 | 문제 |
|------|----------|------|
| LAYER 1 쉽게보면 | "금리와 달러, 지수 흐름이 한 방향으로 정렬되지 않아..." | 정렬됐을 때도 동일 출력 |
| LAYER 2 한줄결론 | "금리 경로, AI 투자 기대, 비트코인 ETF 수급처럼..." | 뉴스 토픽과 무관 |
| LAYER 2 왜중요한지 | 한줄결론과 동일 문장 복붙 | 의미 없는 반복 |
| LAYER 2 뉴스없음 | "오늘 반영할 주요 뉴스가 충분히 수집되지 않았습니다" | 뉴스 1~2건이어도 동일 |
| LAYER 3 한줄결론 | "AI와 반도체 기대가 유지된 구간과, 금리 부담이..." | 하락장에서도 동일 |
| LAYER 3 쉽게보면 | "같은 AI 테마 안에서도 차이가 보였고..." | 데이터 무관 |
| 체크포인트 전체 | "대형 기술주와 반도체의 등락률 차이가 더 커지는지" 등 | 매일 동일 |
| 뉴스 takeaway | 토픽별 4종 고정 문장 | 실제 뉴스 내용 미반영 |

### 1.2 발동 조건

`_fallback_brief`는 OpenAI 생성 브리핑이 구조 검증(`_brief_structure_issues`)을 통과하지 못할 때 발동한다. 데이터 수집이 부분 실패하면 OpenAI도 빈약한 입력으로 불완전한 구조를 생성하기 쉬워 fallback 발동 빈도가 높아진다.

---

## 2. 업계 사례 리서치

### 2.1 뉴스레터 포맷 트렌드 (2025-2026)

업계에서 검증된 금융 뉴스레터 포맷은 크게 3가지로 수렴한다.

**Briefs & Bullets (Morning Brew / The Hustle 계열)**
- 3~5개 brief, 각 150~300단어
- 가장 큰 뉴스가 맨 위, 나머지는 짧게
- 전체 5분 이내 소비 목표
- 별도 bullet 섹션으로 추가 뉴스 링크 제공

**What Happened → Why It Matters (Finimize 계열)**
- 매일 2개 뉴스를 골라 깊이 있게 해석
- 각 뉴스마다 "무슨 일이 있었나 → 왜 중요한가 → 다음에 볼 것" 3단 구조
- 전문 용어 없이 3~5분 소비
- 핵심: 뉴스 개수를 줄이되 해석 깊이를 높임

**All Bullets (Axios / Exec Sum 계열)**
- 100개 이상 bullet으로 업계 전체 커버
- 스캔 가능성 극대화
- 금융 전문가 대상

**현재 프로젝트에 가장 적합한 모델**: Finimize 스타일. 한국 일반 직장인 대상이므로 뉴스 개수보다 해석 깊이가 중요하다.

### 2.2 AI 자동 브리핑 시스템 사례

**AAI Labs Weekly Tech Briefing**
- 4개 소스에서 주 20개 기사 수집 → GPT-4o로 단일 HTML 브리핑 생성
- 핵심 설계: 기사당 "2문장 요약 + 2개 takeaway" 고정 구조
- fallback: HTML 추출 실패 시 메타데이터만으로 요약 생성 (graceful degradation)
- 매주 일요일 무중단 발송 유지

**Zapier Daily Market Briefing Template**
- 복수 소스 모니터링 → 요약 → 이메일 자동 발송
- 핵심: 소스별 가중치를 두고, 수집 실패 소스는 건너뛰되 나머지로 브리핑 생성

### 2.3 Graceful Degradation 패턴 (2025-2026 트렌드)

AI 에이전트 시스템의 graceful degradation은 5단계 계층으로 정리된다:

```
Level 0: Retry     → 같은 호출 재시도 (일시적 오류)
Level 1: Rephrase  → 같은 의도, 다른 파라미터
Level 2: Reroute   → 다른 도구/모델로 같은 작업
Level 3: Replan    → 현재 계획 폐기, 새 계획 생성
Level 4: Escalate  → 부분 결과 반환 또는 사람에게 위임
```

현재 프로젝트의 fallback은 Level 4에 해당하지만, 실제로는 "부분 결과 반환"이 아니라 "고정 템플릿 반환"이다. 개선 방향은 **있는 데이터만으로 동적 부분 결과를 생성**하는 것이다.

**Tiered Model Fallback 패턴**:
```
GPT-4o (전체 기능)
  → 경량 모델 (빠르고 저렴)
    → 로컬 모델 (네트워크 불필요)
      → 캐시/템플릿 응답 (결정적)
```

현재 프로젝트는 마지막 단계(템플릿)만 있다. 중간 단계를 추가하면 품질이 올라간다.

---

## 3. 개선 설계

### 3.1 핵심 원칙

1. **있는 데이터만 말한다**: 수집 실패 항목은 "확인되지 않았습니다"로 처리하되, 성공한 항목은 실제 값 기반으로 해석한다.
2. **고정 문장을 조건 분기로 교체한다**: 지표 방향성(상승/하락/보합)에 따라 해석 문장이 달라져야 한다.
3. **뉴스가 0건이면 뉴스 섹션을 축소한다**: 빈 뉴스에 가짜 해석을 붙이지 않는다.
4. **반복 문장을 제거한다**: 같은 의미가 두 번 나오면 하나를 삭제한다.

### 3.2 변경 대상별 설계

#### A. LAYER 1 "쉽게 보면" — 데이터 기반 분기

현재 (고정):
```
금리와 달러, 지수 흐름이 한 방향으로 정렬되지 않아 미국 장 마감 신호를 함께 비교할 필요가 있습니다.
```

개선 (조건 분기):
```python
def _layer1_easy_summary(macro, indices, korea_watch):
    signals = _collect_direction_signals(macro, indices, korea_watch)
    if signals["aligned_bullish"]:
        return "금리가 안정되고 지수와 선물이 함께 강해, 위험자산 선호가 이어지는 흐름입니다."
    if signals["aligned_bearish"]:
        return "금리 부담과 지수 약세가 겹쳐, 방어적 시각이 우선되는 흐름입니다."
    if signals["mixed"]:
        return "금리와 지수 신호가 엇갈려, 한쪽 방향을 단정하기 어려운 구간입니다."
    return "주요 지표가 충분히 확인되지 않아, 장 마감 후 추가 확인이 필요합니다."
```

#### B. LAYER 2 한줄결론 / 왜중요한지 — 뉴스 토픽 기반

현재 (고정 + 복붙):
```
한줄결론: "금리 경로, AI 투자 기대, 비트코인 ETF 수급처럼..."
왜중요한지: (위와 동일)
```

개선:
```python
def _layer2_headline(news):
    if not news:
        return "오늘은 주요 뉴스가 충분히 수집되지 않아 시장 해석을 보수적으로 유지합니다."
    topics = {item.get("topic") for item in news if item.get("topic")}
    topic_labels = [TOPIC_LABEL_MAP.get(t, t) for t in sorted(topics)]
    return f"오늘 뉴스는 {', '.join(topic_labels)} 쪽에 집중됐습니다."

def _layer2_why_matters(news):
    if len(news) < 2:
        return ""  # 뉴스 부족 시 이 블록 자체를 생략
    # 뉴스 간 공통 흐름을 1문장으로 연결
    ...
```

핵심: `한줄결론`과 `왜중요한지`가 다른 내용을 말하도록 분리한다.

#### C. LAYER 2 뉴스 takeaway — 실제 뉴스 내용 반영

현재 (토픽별 4종 고정):
```python
if topic == "bitcoin":
    return "국내 투자자에게는 비트코인과 관련주 반응을 함께 보는 편이 적절합니다."
```

개선: `why_it_matters` 필드가 있으면 그것을 한국 투자자 관점으로 변환, 없으면 토픽 기반 기본값 사용.
```python
def _fallback_news_takeaway(item):
    wim = item.get("why_it_matters", "").strip()
    if wim:
        return f"국내 투자자에게는 {wim}와 국내 관련주 반응을 함께 볼 필요가 있습니다."
    # 기존 토픽 기반 기본값 유지 (최후방)
    ...
```

#### D. LAYER 3 한줄결론 / 쉽게보면 — 실제 등락 기반

현재 (고정):
```
AI와 반도체 기대가 유지된 구간과, 금리 부담이 먼저 반영된 구간이 함께 나타났습니다.
```

개선:
```python
def _layer3_headline(tech, btc_spot):
    gainers = [p for p in tech if (p.get("change_pct") or 0) > 0.1]
    losers = [p for p in tech if (p.get("change_pct") or 0) < -0.1]
    if gainers and losers:
        top = gainers[0]["label"]
        bottom = losers[0]["label"]
        return f"오늘은 {top} 등이 강했고 {bottom} 등은 약했습니다."
    if gainers:
        return f"기술주 전반이 상승했고, {gainers[0]['label']}의 상승폭이 가장 컸습니다."
    if losers:
        return f"기술주 전반이 약했고, {losers[0]['label']}의 하락폭이 가장 컸습니다."
    return "주요 종목 등락률이 충분히 확인되지 않았습니다."
```

#### E. 체크포인트 — 당일 데이터 기반 동적 생성

현재 (고정):
```
- 대형 기술주와 반도체의 등락률 차이가 더 커지는지
- VIX, 달러 인덱스, 미국 10년물 금리와 위험자산 반응이 다시 엇갈리는지
```

개선: 실제 이상값이나 주목할 지표를 기반으로 생성.
```python
def _dynamic_checkpoints(macro, indices, tech, btc):
    points = []
    vix = _point_price(_point_by_key(macro, "vix"))
    if vix and vix > 20:
        points.append(f"VIX가 {vix:.1f}로 높은 편이라 변동성이 줄어드는지")
    nq_change = _point_change_pct(_point_by_key(korea_watch, "nq_futures"))
    if nq_change and abs(nq_change) > 0.5:
        direction = "상승" if nq_change > 0 else "하락"
        points.append(f"나스닥 선물 {direction} 흐름이 본장에서도 이어지는지")
    # ... 데이터 기반으로 2~3개 생성
    if not points:
        points.append("장 마감 후 주요 지표 방향이 정리되는지")
    return points[:3]
```

#### F. 뉴스 0건 시 LAYER 2 축소

현재: 뉴스 0건이어도 "핵심 이슈", "왜 중요한지", "체크포인트" 전체 구조를 유지하며 가짜 해석을 채운다.

개선: 뉴스 0건이면 LAYER 2를 한 블록으로 축소.
```
2. LAYER 2 | 주요 뉴스
한줄 결론
오늘은 주요 뉴스가 충분히 수집되지 않았습니다. 장중 주요 매체를 직접 확인하는 편이 적절합니다.
```

---

## 4. 구현 우선순위

| 순위 | 항목 | 영향도 | 난이도 |
|------|------|--------|--------|
| 1 | LAYER 2 한줄결론/왜중요한지 복붙 제거 + 뉴스 0건 축소 | 높음 | 낮음 |
| 2 | LAYER 1/3 고정 해석을 지표 방향 분기로 교체 | 높음 | 중간 |
| 3 | 뉴스 takeaway를 `why_it_matters` 기반으로 개선 | 중간 | 낮음 |
| 4 | 체크포인트를 당일 데이터 기반 동적 생성으로 교체 | 중간 | 중간 |
| 5 | LAYER 3 한줄결론을 실제 등락 기반으로 교체 | 중간 | 낮음 |

---

## 5. 검증 기준

- fallback 브리핑을 연속 3일 생성했을 때 동일 문장이 나오지 않아야 한다 (데이터가 다르면 문장도 달라야 한다).
- 뉴스 0건 / 1건 / 5건 각각에서 LAYER 2 출력이 적절히 달라져야 한다.
- 모든 지표가 missing일 때도 에러 없이 "확인되지 않았습니다" 계열로 처리되어야 한다.
- 기존 `_brief_structure_issues` 검증을 통과해야 한다 (3 LAYER 구조 유지).

---

## 6. 참고 자료

- [AAI Labs: Automated Weekly Tech Briefing System](https://aai-labs.com/en/blogs/how-we-built-an-automated-weekly-tech-briefing-system) — 다중 소스 수집 + AI 요약 파이프라인 설계
- [Newsletter Operator: 10 Best Newsletter Types and Templates](https://www.newsletteroperator.com/p/10-best-newsletter-types-and-templates) — Briefs & Bullets, TLDR, All Bullets 등 포맷 비교
- [Finimize Daily Brief](https://finimize.com/newsletter) — "무슨 일 → 왜 중요 → 다음에 볼 것" 3단 구조
- [Error Recovery and Graceful Degradation in AI Agents](https://notes.muthu.co/2026/02/error-recovery-and-graceful-degradation-in-ai-agents/) — 5단계 retry 계층, tiered model fallback, checkpoint-and-resume 패턴
- [Graceful Degradation in AI Systems](https://michaeljohnpena.com/blog/2024-09-25-graceful-degradation-ai) — 부분 기능 유지 설계 원칙
- [Zapier Daily Market Briefing Template](https://templates.vercel.zapier.com/templates/details/daily-market-competitive-briefing-automation) — 소스별 가중치 + 실패 소스 건너뛰기 패턴
