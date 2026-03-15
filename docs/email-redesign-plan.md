# 이메일 브리핑 전면 개선 계획 (2026-03-15)

> 3-Provider 아키텍처(Sonar + Grok X Keyword + Grok Web Search) 데이터를 브리핑에 누락 없이 전달하고, 2026 이메일 디자인 트렌드를 반영해 사용자 경험을 근본적으로 개선한다.

---

## 2026 이메일 디자인 트렌드 대비 현황 분석

### 현재 템플릿 vs 2026 트렌드

| 영역 | 2026 트렌드 | 현재 상태 | 갭 |
|---|---|---|---|
| **배경색** | 오프화이트(`#F5F5F0`~`#FAF9F6`) — 눈의 피로 감소, 다크모드 반전 시 부드러움 | `#f8fafc` (블루이시 그레이) | ⚠️ 약간 차가운 톤, 개선 여지 |
| **카드 배경** | 다크모드에서 그레이스케일 중간톤(`#1e293b`) | `#1e293b` | ✅ 적합 |
| **카드 라운딩** | 16~20px 트렌드 (과도한 라운딩 지양) | `24px` | ⚠️ 약간 과도 |
| **그림자** | 미니멀 그림자 또는 제거 추세 | `0 12px 30px rgba(15,23,42,0.06)` | ⚠️ 과도한 확산 |
| **폰트 크기** | 본문 15~16px, 헤드라인 22~28px | 본문 15px, 헤드라인 26px | ✅ 적합 |
| **라벨 크기** | 최소 12px (접근성) | 카드 라벨 13px, 서브라벨 11~12px | ⚠️ 서브라벨 11px 미달 |
| **행간** | 1.5x~1.6x 본문 | `line-height: 1.6` | ✅ 적합 |
| **CTA** | 44x44px 최소 터치 타겟, 고대비 단일 액센트 | 텍스트 링크만 (구독해지/GitHub) | ❌ CTA 부재 |
| **Smart Brevity** | 볼드 헤드라인 → "Why it matters" → bullet 디테일 | 뉴스 카드에 부분 적용 | ⚠️ 불완전 |
| **정보 밀도** | 섹션 간 여백 넉넉히, 섹션 내 밀도 높게 | 카드 간 14px 균일 | ⚠️ 시각적 위계 부족 |
| **다크모드** | 82.7% 모바일 사용자 — `prefers-color-scheme` + 중간톤 팔레트 필수 | 기본 지원 있음 | ⚠️ `.pct-down`, 링크색 누락 |
| **모바일 반응형** | 600px 기준, fluid-hybrid, 터치 타겟 44px | max-width 640px, 일부 반응형 | ⚠️ 터치 타겟 미검증 |
| **타이포그래피 위계** | 타이포그래피가 주인공 — 이미지 대신 글꼴 크기/굵기로 시선 유도 | 부분 적용 (요약 26px vs 본문 15px) | ⚠️ 중간 단계 부재 |
| **색상 팔레트** | 뮤트 뉴트럴 + 고대비 단일 액센트 | 블루 계열 `#1e40af` 라벨 | ⚠️ 액센트 통일 안됨 |
| **preheader** | 40~130자, 핵심 수치 포함으로 열람률 상승 | 요약 2줄 이어붙이기 | ⚠️ 수치 미포함 |
| **List-Unsubscribe** | Gmail/Yahoo 2024년부터 필수 | 미지원 | ❌ 필수 누락 |

### 핵심 갭 요약

1. **정보 위계 부족** — 카드 간 시각적 무게 차이가 없어 모든 섹션이 동일 중요도로 보임
2. **CTA 부재** — 이메일 목적(읽고 → 행동)에 맞는 액션 유도 요소 없음
3. **다크모드 불완전** — 퍼센트 하락 색상, 링크 색상 등 세부 요소 누락
4. **타이포 중간 단계 없음** — 26px(요약) → 18px(뉴스 헤드라인) → 15px(본문) 사이 갭
5. **카드 스타일 과도** — 24px 라운딩 + 큰 그림자가 2026년 미니멀 트렌드와 불일치

---

## 현황 진단

### 데이터 전달 경로 갭

| 데이터 | pipeline.py → packet | prompting.py → LLM | 상태 |
|---|---|---|---|
| `topic_summaries` (Sonar) | ✅ `packet["topic_summaries"]` | ❌ `news_focus_json`에 미포함 | **LLM 미참조** |
| `x_market_signals` (Grok X) | ✅ `packet["x_market_signals"]` | ❌ `news_focus_json`에 미포함 | **LLM 미참조** |
| `news` (병합 뉴스) | ✅ `packet["news"]` | ✅ `news_focus_json.top_items` | 정상 |

`_build_news_focus()`가 `packet["news"]` 상위 5개만 추출하고 신규 데이터를 무시함.
`brief_instructions.j2`에 신규 데이터 활용 지시 없음.

### 이메일 정보 소멸 맵

프롬프트가 생성하는 15개 블록 중 7개(47%)가 이메일에서 소멸:

| 블록 | 이메일 표시 | 상태 |
|---|---|---|
| L1 한줄 결론 | 핵심 요약 카드 1번째 줄 | ✅ |
| L1 핵심 수치 | (없음) | ❌ 소멸 |
| L1 쉽게 보면 (코스피 영향) | (없음) | ❌ 소멸 |
| L1 오늘 체크할 포인트 | (없음) | ❌ 소멸 |
| L2 한줄 결론 | 핵심 요약 카드 2번째 줄 | ✅ |
| L2 핵심 이슈 | 뉴스 카드 bullet | ⚠️ 파싱 의존 |
| L2 왜 중요한지 | (없음) | ❌ 소멸 |
| L2 오늘 체크할 포인트 | (없음) | ❌ 소멸 |
| L3 한줄 결론 | 핵심 요약 카드 3번째 줄 | ✅ |
| L3 주요 지표 | 시장 흐름 카드 | ⚠️ 파싱 의존 |
| L3 거시 지표 | 거시 지표 카드 | ⚠️ 키워드 매칭 의존 |
| L3 쉽게 보면 | (없음) | ❌ 소멸 |
| L3 오늘 체크할 포인트 | (없음) | ❌ 소멸 |
| 참고 출처 | 데이터 출처 카드 | ✅ |
| 데이터 처리 메모 | 거시 지표 카드 하단 | ✅ |

---

## 트랙 A — 데이터 전달 경로 완성

LLM이 Sonar 토픽 요약과 X 시그널을 실제로 참조할 수 있게 한다.

### A-1. `_build_news_focus()` 확장

**파일**: `src/morning_brief/prompting.py`

반환 dict에 신규 키 2개 추가:

```python
return {
    "top_items": top_items,
    "topics": topics,
    "official_signals": official_signals,
    "topic_summaries": packet.get("topic_summaries", []),
    "x_market_signals": packet.get("x_market_signals", []),
}
```

### A-2. `brief_input.j2` 지시문 추가

**파일**: `src/morning_brief/prompts/brief_input.j2`

`news_focus_json` 블록 아래에 추가:

```
Sonar 토픽 요약과 X 시장 시그널은 news_focus_json 안에 포함되어 있다.
- `topic_summaries`: 토픽별 구조화된 요약 (summary, why_it_matters, citations)
- `x_market_signals`: 실시간 X 키워드 시그널 (headline, summary, sentiment, source_handle)
```

### A-3. `brief_instructions.j2` 활용 지시 추가

**파일**: `src/morning_brief/prompts/brief_instructions.j2`

작성 지침 블록에 추가:

```
- `news_focus_json`의 `topic_summaries`가 있으면, 각 토픽의 `summary`를 LAYER 2 뉴스 해석의 출발점으로 사용하고, `why_it_matters`를 "왜 중요한지" 블록에 반영한다.
- `topic_summaries`의 `citations`는 해당 토픽 뉴스의 근거 URL로 하단 참고 출처에 포함한다.
- `news_focus_json`의 `x_market_signals`가 있으면, `sentiment`(bullish/bearish/neutral)를 LAYER 1 판단 근거의 보조 시그널로 참고한다.
- `x_market_signals`의 `headline`과 `why_it_matters`는 LAYER 2 핵심 이슈 bullet의 후보로 사용할 수 있다.
- `x_market_signals`의 `source_handle`이 @DeItaone, @FirstSquawk 등 속보 계정이면 시장 반응 속도가 빠른 뉴스로 우선 반영한다.
```

---

## 트랙 B — 이메일 구조 재설계

### 목표 이메일 구조

```
┌─────────────────────────────────┐
│ Morning Market Brief            │
│ 2026년 3월 16일 월요일          │
├─────────────────────────────────┤
│ [데이터 품질 알림] (있을 때만)  │
├─────────────────────────────────┤
│ ① 오늘 핵심 요약               │
│   시장 판단  "오늘은 관망..."   │
│   뉴스      "연준 발언이..."    │
│   종목      "반도체가..."       │
│   ─────────                     │
│   · 원/달러 1,342원 (+0.3%)     │  ← 핵심 수치 (신규)
│   · 나스닥 선물 약보합          │
│   · 공포탐욕 32 (공포)          │
│   ─────────                     │
│   🇰🇷 코스피 영향: ...          │  ← 코스피 한줄 (신규)
├─────────────────────────────────┤
│ ② 📰 주요 뉴스                 │
│   "금리·달러 흐름이 겹치며..."  │  ← 왜 중요한지 (신규)
│   ─────────                     │
│   헤드라인 / 시장 의미 / 관점   │
│   (반복 3~5건)                  │
├─────────────────────────────────┤
│ ③ 📊 시장 흐름                 │
│   🟢 상승 종목                  │  ← 상승/하락 분리 (신규)
│   🔴 하락 종목                  │
├─────────────────────────────────┤
│ ④ 🔢 거시 지표                 │
│   라벨 | 값                     │
├─────────────────────────────────┤
│ ⑤ 🎯 오늘 체크할 포인트        │  ← 신규 카드
│   · FOMC 의사록 공개 주시       │
│   · 엔비디아 GTC 컨퍼런스       │
├─────────────────────────────────┤
│ ⑥ 📎 데이터 출처               │
├─────────────────────────────────┤
│ 면책 · 구독해지 · GitHub        │
└─────────────────────────────────┘
```

### B-1. `거시 지표` 소제목 인식

**파일**: `src/morning_brief/brief_formatting.py`

```python
MACRO_LABELS = {"거시 지표", "거시 환경"}
# SECTION_KIND_BY_LABEL에 추가
{label: "macro" for label in MACRO_LABELS}
# split_section_groups() 반환값에 "macro" 그룹 추가
```

### B-2. `_build_email_context()` 확장

**파일**: `src/morning_brief/emailer.py`

신규 컨텍스트 변수:

| 변수 | 소스 | 용도 |
|---|---|---|
| `key_metrics` | LAYER 1 `metrics` 그룹 첫 3줄 | 핵심 수치 bullet |
| `kospi_impact` | LAYER 1 `insight` 그룹에서 "코스피" 포함 문장 | 코스피 영향 한줄 |
| `news_context` | LAYER 2 `insight` 그룹 첫 문단 | "왜 중요한지" 요약 |
| `watch_items` | 각 레이어 `watch` 그룹 bullet 수집 (최대 5개) | 체크포인트 카드 |
| `summary_labels` | `["시장 판단", "뉴스", "종목"]` 고정 | 요약 라벨 |
| `stock_up_rows` | `stock_rows` 중 `tone == "up"` | 상승 종목 그룹 |
| `stock_down_rows` | `stock_rows` 중 `tone != "up"` | 하락 종목 그룹 |

### B-3. `_build_stock_rows()` 상승/하락 분리

**파일**: `src/morning_brief/emailer.py`

기존 `_build_stock_row()`가 이미 `tone` (up/down/flat)을 반환. 컨텍스트에서 분리:

```python
stock_up_rows = [r for r in stock_rows if r.tone == "up"]
stock_down_rows = [r for r in stock_rows if r.tone != "up"]
```

### B-4. `email.html.j2` 카드 구조 재설계

**파일**: `src/morning_brief/templates/email.html.j2`

변경 사항:

1. **핵심 요약 카드**
   - `top_summary_lines` 각 줄 앞에 `summary_labels[loop.index0]` 라벨 추가 (11px, `#64748b`, bold)
   - 구분선 아래 `key_metrics` bullet 렌더링 (15px, `#334155`, tabular-nums)
   - `kospi_impact`가 있으면 배경색 `#f0fdf4` 박스로 렌더링

2. **뉴스 카드**
   - 카드 라벨 아래, 뉴스 bullet 위에 `news_context` 문단 추가 (13px, italic, `#475569`)
   - 뉴스 0건 + fallback 비어있으면 기본 안내: "주말/휴일로 주요 뉴스 업데이트가 없습니다."

3. **시장 흐름 카드**
   - `stock_up_rows`가 있으면 `🟢 상승` 그룹 헤더
   - `stock_down_rows`가 있으면 `🔴 하락` 그룹 헤더

4. **체크포인트 카드 (신규)**
   - 거시 지표 카드와 출처 카드 사이에 배치
   - 아이콘: 🎯, 라벨: "오늘 체크할 포인트", 색상: `#7c3aed`
   - `watch_items` bullet 렌더링

### B-5. 뉴스 bullet 파싱 안정화

**파일**: `src/morning_brief/emailer.py`

#### `_parse_news_metric_line()`
```python
# 현재: line.split("|") 만 사용
# 개선: | 가 1개 이하면 — 또는 – 로 재시도
parts = [part.strip() for part in line.split("|")]
if len(parts) < 2:
    parts = [part.strip() for part in re.split(r"\s*[—–]\s*", line)]
```

#### `_stock_name_from_line()`
```python
# 현재: re.split(r"(은|는|이|가)\s*$", prefix)
# 개선: 괄호 뒤 조사 매칭 허용
cleaned = re.split(r"(?:\([^)]*\))?\s*(은|는|이|가)\s", prefix)[0].strip()
```

#### `_split_macro_line()`
```python
# 현재: "는 ", "은 " 만 체크
# 추가: "가 ", "이 " 도 체크
for particle in ("는 ", "은 ", "가 ", "이 "):
    if particle in normalized_line:
        label, value = normalized_line.split(particle, 1)
        return label.strip() or "거시 지표", value.strip() or normalized_line
```

### B-6. preheader 최적화

**파일**: `src/morning_brief/emailer.py` — `_build_email_context()`

```python
# 현재: top_summary_lines[:2] → 140자
# 개선: key_metrics가 있으면 핵심 수치를 preheader에 포함
if key_metrics:
    preheader = " · ".join(m.lstrip("- ") for m in key_metrics[:3])[:140]
else:
    preheader = " / ".join(top_summary_lines[:2]).strip()[:140]
```

### B-7. 파싱 실패 fallback 개선

**파일**: `src/morning_brief/emailer.py`

- `_fallback_section_text()`: 소제목 라벨을 제거하고 본문만 반환
- 뉴스 0건 + fallback 비어있으면 기본 안내 메시지 설정

---

## 트랙 C — 프롬프트-파서 계약 강화 + 이메일 품질

### C-1. 프롬프트에 파서 친화적 제약 추가

**파일**: `src/morning_brief/prompts/brief_instructions.j2`

`output_contract`에 추가:

```
- LAYER 2 `핵심 이슈` bullet의 `|` 구분자는 반드시 3개 필드(헤드라인 | 시장 의미 | 한국 투자자 관점)로 유지한다. 헤드라인 안에 `|` 문자를 쓰지 않는다.
- LAYER 3 `주요 지표` bullet에서 종목명 뒤에는 반드시 `은/는` 조사를 사용한다.
- LAYER 3 `거시 지표` 소제목은 반드시 별도 줄에 단독으로 쓴다.
```

### C-2. `List-Unsubscribe` 헤더 추가

**파일**: `src/morning_brief/emailer.py` — `build_briefing_message()`

```python
msg["List-Unsubscribe"] = f"<{_unsubscribe_url(sender)}>"
msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
```

### C-3. 다크모드 색상 대비 보강

**파일**: `src/morning_brief/templates/email.html.j2`

```css
@media (prefers-color-scheme: dark) {
  .pct-down { color: #f87171 !important; }
  .text-muted { color: #cbd5e1 !important; }
}
```

---

## 트랙 D — 2026 디자인 트렌드 반영

> 리서치 기반: Axios Smart Brevity, Finimize, Morning Brew 등 금융 뉴스레터 + 2026 이메일 디자인 트렌드

### D-1. 배경색 & 카드 스타일 현대화

**파일**: `src/morning_brief/templates/email.html.j2`

**배경색 — 오프화이트 전환**
```css
/* Before */
body { background: #f8fafc; }  /* 차가운 블루이시 그레이 */

/* After */
body { background: #f5f5f0; }  /* 따뜻한 오프화이트 — 눈 피로 감소, 다크모드 반전 시 부드러움 */
```

**카드 라운딩 & 그림자 축소**
```css
/* Before */
.card { border-radius: 24px; box-shadow: 0 12px 30px rgba(15,23,42,0.06); }

/* After */
.card { border-radius: 16px; box-shadow: 0 2px 8px rgba(15,23,42,0.04); }
```

**다크모드 배경도 함께 조정**
```css
@media (prefers-color-scheme: dark) {
  body, .shell { background: #111111 !important; }  /* 순수 검정 대신 다크 그레이 */
  .card { background: #1a1a1a !important; border-color: #2a2a2a !important; }
}
```

**근거**: 2026년 트렌드는 과도한 라운딩/그림자에서 벗어나 미니멀한 카드 스타일. 오프화이트 배경은 다크모드 자동 반전 시 `#0a0a0f` 수준으로 변환되어 순수 흑백보다 눈에 편안함.

### D-2. 타이포그래피 위계 강화

**파일**: `src/morning_brief/templates/email.html.j2`

현재 글꼴 크기 단계: `26px → 18px → 15px → 13px` (4단계)
개선 후: `28px → 20px → 16px → 13px → 12px` (5단계)

| 용도 | 현재 | 개선 | 비고 |
|---|---|---|---|
| L1 요약 첫 줄 | 26px / 800 | **28px / 800** | 히어로 텍스트 — 시선 즉시 포착 |
| L1 요약 2~3번째 줄 | 17px / 700 | **18px / 700** | 서브 요약 — 가독성 유지 |
| 뉴스 헤드라인 | 18px / 800 | **20px / 800** | Smart Brevity 핵심 — 볼드 헤드라인이 주인공 |
| 본문 (시장 의미 등) | 15px / 400 | **16px / 400** | 2026 최소 권장 본문 크기 |
| 카드 라벨 | 13px / 600 | 13px / 600 | 유지 |
| 서브라벨 (시장 의미, 관점) | 12px / 700 | **13px / 700** | 접근성 최소 12px 충족하되 여유 확보 |
| 소스/메모 | 12~13px | 12px | 유지 (부가 정보) |

**서체 스택 최적화**
```css
/* 현재 */
font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Noto Sans KR', 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif;

/* 개선 — 한글 우선순위 조정 */
font-family: 'Apple SD Gothic Neo', 'Noto Sans KR', -apple-system, BlinkMacSystemFont, 'Malgun Gothic', 'Segoe UI', Roboto, sans-serif;
```

**근거**: 한국어 뉴스레터이므로 한글 전용 서체를 시스템 서체보다 우선 배치. `Apple SD Gothic Neo`는 macOS/iOS에서 가장 깔끔한 한글 렌더링 제공. `Noto Sans KR`은 Android/Linux 커버.

### D-3. 정보 위계 — 카드 간 시각적 무게 차등

**파일**: `src/morning_brief/templates/email.html.j2`

**히어로 카드 (핵심 요약) — 강조**
```html
<!-- 핵심 요약 카드만 상단 액센트 보더 추가 -->
<table class="card" style="...border-top: 4px solid #1e40af; border-radius: 0 0 16px 16px;">
```

**일반 카드 (뉴스, 시장 흐름) — 기본**
```html
<!-- 기존과 동일하되 라운딩/그림자만 축소 -->
<table class="card" style="...border-radius: 16px; box-shadow: 0 2px 8px rgba(15,23,42,0.04);">
```

**서브 카드 (거시 지표, 체크포인트) — 배경 구분**
```html
<!-- 오프화이트 대비 약간 더 진한 배경으로 시각 구분 -->
<table class="card section-fill" style="...background: #eeeee8; border-radius: 16px; box-shadow: none;">
```

**체크포인트 카드 — 액센트 컬러**
```html
<!-- 보라색 좌측 보더로 액션 유도 -->
<table class="card" style="...border-left: 4px solid #7c3aed; border-radius: 0 16px 16px 0;">
```

**근거**: Axios/Morning Brew 패턴 — 첫 번째 카드가 시각적으로 가장 무겁고, 하단으로 갈수록 가벼워지는 정보 위계. 좌측 보더는 "액션 필요" 시그널로 금융 뉴스레터에서 보편적.

### D-4. Smart Brevity 패턴 적용

**파일**: `src/morning_brief/templates/email.html.j2` + `src/morning_brief/prompts/brief_instructions.j2`

Axios Smart Brevity 구조: **볼드 헤드라인 → "Why it matters" 1문장 → 디테일 bullet**

**뉴스 카드 구조 변경**
```
현재:
  헤드라인 (18px bold)
  시장 의미 ← 라벨
  본문 텍스트
  국내 투자자 관점 ← 라벨
  본문 텍스트

개선:
  헤드라인 (20px bold)
  ↳ 시장 의미 (16px, 본문과 구분 없이 자연스럽게)  ← "Why it matters" 역할
  💡 한국 투자자: 본문 텍스트 (13px muted)           ← 인라인 라벨로 간결화
```

**변경 내용**:
- "시장 의미" 라벨 제거 → 헤드라인 바로 아래 자연스러운 본문 배치 (Smart Brevity의 "What's happening" → "Why it matters" 흐름)
- "국내 투자자 관점" → 인라인 `💡 한국 투자자:` prefix로 축약 (별도 라벨 제거)
- 뉴스 항목 간 구분선 유지하되 간격 축소 (`margin-top: 16px` → `12px`)

**근거**: Smart Brevity 핵심은 라벨 오버헤드를 줄이고 자연스러운 읽기 흐름 유지. 별도 라벨 2개(`시장 의미`, `국내 투자자 관점`)는 시선을 분산시킴.

### D-5. 다크모드 완전 대응

**파일**: `src/morning_brief/templates/email.html.j2`

현재 다크모드 CSS에 누락된 요소들 추가:

```css
@media (prefers-color-scheme: dark) {
  /* 기존 유지 */
  body, .shell { background: #111111 !important; }
  .card { background: #1a1a1a !important; border-color: #2a2a2a !important; box-shadow: none !important; }
  .section-fill { background: #1f1f1f !important; }
  .text-strong, .text-body, .text-link { color: #e8e8e3 !important; -webkit-text-fill-color: #e8e8e3 !important; }
  .text-subtle, .text-muted, .source-name { color: #9ca3af !important; -webkit-text-fill-color: #9ca3af !important; }
  .rule { border-color: #2a2a2a !important; }

  /* 신규 — 누락 요소 */
  .pct-up { color: #4ade80 !important; -webkit-text-fill-color: #4ade80 !important; }      /* 상승: 밝은 녹색 */
  .pct-down { color: #f87171 !important; -webkit-text-fill-color: #f87171 !important; }    /* 하락: 밝은 빨강 */
  .pct-flat { color: #9ca3af !important; -webkit-text-fill-color: #9ca3af !important; }    /* 보합: 회색 */
  a { color: #93c5fd !important; }                                                           /* 링크: 밝은 블루 */
  .notice-card { background: #331a00 !important; border-color: #92400e !important; color: #fbbf24 !important; } /* 알림 카드 */
  .hero-accent { border-color: #3b82f6 !important; }                                        /* 히어로 상단 보더 */
  .watch-accent { border-color: #a78bfa !important; }                                       /* 체크포인트 좌측 보더 */
  .kospi-box { background: #14291e !important; }                                             /* 코스피 박스 */
}
```

**대비 비율 검증**:
| 요소 | 전경색 | 배경색 | 대비 비율 | WCAG AA |
|---|---|---|---|---|
| 본문 텍스트 | `#e8e8e3` | `#1a1a1a` | 13.2:1 | ✅ |
| 서브텍스트 | `#9ca3af` | `#1a1a1a` | 6.3:1 | ✅ |
| 상승 퍼센트 | `#4ade80` | `#1a1a1a` | 8.7:1 | ✅ |
| 하락 퍼센트 | `#f87171` | `#1a1a1a` | 5.4:1 | ✅ |
| 링크 | `#93c5fd` | `#1a1a1a` | 8.1:1 | ✅ |

### D-6. 모바일 반응형 강화

**파일**: `src/morning_brief/templates/email.html.j2`

```css
@media screen and (max-width: 600px) {
  /* 기존 유지 */
  .shell-pad { padding: 12px 8px !important; }
  .card-pad { padding: 16px !important; }
  .hero-title { font-size: 24px !important; }
  .layer-one { font-size: 22px !important; }

  /* 신규 추가 */
  .news-headline { font-size: 18px !important; }       /* 데스크톱 20px → 모바일 18px */
  .text-body { font-size: 15px !important; }            /* 데스크톱 16px → 모바일 15px */
  .macro-label { width: 35% !important; }               /* 거시 지표 라벨 폭 확대 (좁은 화면) */
  .source-row td { display: block !important; }         /* 출처 2열 → 1열 스택 */
  .card { border-radius: 12px !important; }             /* 모바일에서 라운딩 더 축소 */

  /* 터치 타겟 — 44px 최소 */
  a { min-height: 44px; display: inline-block; line-height: 44px; }
  .footer-link { padding: 8px 16px !important; }
}
```

**근거**: 이메일 열람의 41%가 모바일. Gmail 모바일은 media query를 지원하지만, Gmail 데스크톱은 지원하지 않으므로 데스크톱 기본값이 inline style에, 모바일 오버라이드가 media query에 위치해야 함.

### D-7. 핵심 요약 카드 — "글랜스 가능" 디자인

**파일**: `src/morning_brief/templates/email.html.j2`

현재 핵심 요약 카드는 3줄 텍스트만 나열. 2026 금융 뉴스레터 패턴은 **"5초 안에 핵심 파악"** 구조:

```
┌─ 히어로 카드 ────────────────────────┐
│ ┌──────────────────────────────────┐ │
│ │ 오늘은 관망 ← 28px bold         │ │
│ │ 나스닥 약보합 속 금리 불확실... │ │
│ └──────────────────────────────────┘ │
│                                      │
│ 시장  연준 발언 앞두고 경계감 확산   │ ← 라벨 + 요약 한 줄
│ 종목  반도체 혼조, AI 테마 차별화    │ ← 라벨 + 요약 한 줄
│ ──────────────────────────────────── │
│ 원/달러 1,342(+0.3%) · NQ -0.2%     │ ← 핵심 수치 인라인
│ · 공포탐욕 32(공포)                  │
│ ──────────────────────────────────── │
│ 🇰🇷 코스피: 미 증시 약보합에 연동,  │ ← 코스피 박스
│    개장 초 -0.3% 수준 예상           │
└──────────────────────────────────────┘
```

**변경 사항**:
- 첫 줄(시장 판단)을 **배경색 박스**(`#f0f4ff`)로 감싸서 시선 고정
- 2~3번째 줄에 `summary_labels` 인라인 라벨 추가 (13px bold `#64748b`)
- 핵심 수치를 `·` 구분 인라인으로 렌더링 (줄바꿈 최소화)
- 코스피 영향을 **라운드 박스**(`#f0fdf4`, 패딩 12px, border-radius 8px)로 강조

### D-8. 이메일 클라이언트 호환성 보장

**인라인 CSS 원칙**: Gmail 데스크톱이 `<head>` 스타일을 제거하므로, 모든 핵심 스타일은 inline style에 위치. `<head>`의 CSS는 다크모드/모바일 **오버라이드 전용**.

**Outlook Desktop (Word 렌더 엔진) 대응**:
```html
<!--[if mso]>
<style>
  .card { border-radius: 0 !important; }
  .hero-accent { border-top: 4px solid #1e40af !important; }
</style>
<![endif]-->
```

**테스트 매트릭스**:
| 클라이언트 | 렌더 엔진 | 주의사항 |
|---|---|---|
| Apple Mail | WebKit | 모든 CSS 지원 — 기준 클라이언트 |
| Gmail 모바일 | Custom DOM | `<head>` 제거, inline만 적용, media query 부분 지원 |
| Gmail 데스크톱 | Custom DOM | media query 미지원, `<head>` 제거 |
| Outlook Desktop | MS Word HTML | `border-radius`, `box-shadow` 미지원 — conditional comment로 대응 |
| Outlook New (Web) | 웹 기반 | 대부분 지원 — MS가 2025~2026 전환 중 |
| Naver Mail | Custom | inline 기본, media query 부분 지원 |

---

## 구현 순서 (의존성 기반)

| 순서 | 작업 | 트랙 | 파일 | 의존 |
|------|------|------|------|------|
| 1 | `_build_news_focus()` 확장 | A-1 | `prompting.py` | 없음 |
| 2 | `brief_input.j2` 지시문 추가 | A-2 | `brief_input.j2` | A-1 |
| 3 | `brief_instructions.j2` 활용 지시 + 파서 제약 | A-3, C-1 | `brief_instructions.j2` | A-1 |
| 4 | `거시 지표` 소제목 인식 | B-1 | `brief_formatting.py` | 없음 |
| 5 | 뉴스 bullet/종목명/거시 파싱 안정화 | B-5 | `emailer.py` | B-1 |
| 6 | `_build_email_context()` 확장 | B-2 | `emailer.py` | B-1, B-5 |
| 7 | 상승/하락 분리 | B-3 | `emailer.py` | B-2 |
| 8 | preheader 최적화 + fallback 개선 | B-6, B-7 | `emailer.py` | B-2 |
| 9 | 배경색/카드 스타일/타이포 현대화 | D-1, D-2 | `email.html.j2` | 없음 (병렬 가능) |
| 10 | 정보 위계 차등 + Smart Brevity | D-3, D-4 | `email.html.j2` | D-1 |
| 11 | 히어로 카드 글랜스 디자인 | D-7 | `email.html.j2` | B-2, D-2 |
| 12 | `email.html.j2` 카드 구조 재설계 (통합) | B-4 | `email.html.j2` | B-2, B-3, D-3, D-7 |
| 13 | 다크모드 완전 대응 | D-5, C-3 | `email.html.j2` | D-1 |
| 14 | 모바일 반응형 강화 | D-6 | `email.html.j2` | D-1, D-2 |
| 15 | Outlook 호환성 + List-Unsubscribe | D-8, C-2 | `email.html.j2`, `emailer.py` | D-1 |

---

## 커밋 단위

| # | 메시지 | 트랙 | 순서 |
|---|---|---|---|
| 1 | `feat(prompt): Sonar/X 시그널 데이터 전달 경로 완성` | A 전체 | 1~3 |
| 2 | `feat(email): 이메일 구조 재설계 — 핵심 수치/체크포인트/상승하락 분리` | B 전체 | 4~8 |
| 3 | `feat(email): 2026 디자인 트렌드 — 배경/타이포/위계/Smart Brevity` | D-1~D-4, D-7 | 9~12 |
| 4 | `fix(email): 다크모드 완전 대응 + 모바일 반응형 강화` | D-5, D-6, C-3 | 13~14 |
| 5 | `fix(email): Outlook 호환 + List-Unsubscribe + 파서 계약 강화` | D-8, C-2, C-1 | 15 |

---

## 소멸 정보 복원 체크리스트

| 블록 | 현재 | 개선 후 | 작업 |
|---|---|---|---|
| L1 핵심 수치 | ❌ 소멸 | ✅ 핵심 요약 카드 하단 | B-2, B-4 |
| L1 쉽게 보면 (코스피) | ❌ 소멸 | ✅ 핵심 요약 카드 하단 | B-2, B-4 |
| L1 오늘 체크할 포인트 | ❌ 소멸 | ✅ 체크포인트 카드 | B-2, B-4 |
| L2 왜 중요한지 | ❌ 소멸 | ✅ 뉴스 카드 상단 | B-2, B-4 |
| L2 오늘 체크할 포인트 | ❌ 소멸 | ✅ 체크포인트 카드 | B-2, B-4 |
| L3 쉽게 보면 | ❌ 소멸 | ⚠️ 시장 흐름 카드 통합 검토 | — |
| L3 오늘 체크할 포인트 | ❌ 소멸 | ✅ 체크포인트 카드 | B-2, B-4 |
| Sonar topic_summaries | ❌ LLM 미참조 | ✅ news_focus_json 포함 | A-1 |
| X market signals | ❌ LLM 미참조 | ✅ news_focus_json 포함 | A-1 |

**소멸률: 47% → 7%** (L3 쉽게 보면만 판단 보류)

---

## 수정 대상 파일 요약

| 파일 | 트랙 | 변경 유형 |
|---|---|---|
| `src/morning_brief/prompting.py` | A-1 | `_build_news_focus()` 반환값 확장 |
| `src/morning_brief/prompts/brief_input.j2` | A-2 | 신규 데이터 블록 지시문 추가 |
| `src/morning_brief/prompts/brief_instructions.j2` | A-3, C-1 | 활용 지시 + 파서 제약 추가 |
| `src/morning_brief/brief_formatting.py` | B-1 | `MACRO_LABELS` + `macro` 그룹 추가 |
| `src/morning_brief/emailer.py` | B-2~B-7, C-2 | 컨텍스트 확장, 파싱 안정화, fallback, List-Unsubscribe |
| `src/morning_brief/templates/email.html.j2` | B-4, C-3, D 전체 | 카드 구조 재설계, 디자인 현대화, 다크모드 완전 대응, 모바일 강화, Outlook 호환 |
