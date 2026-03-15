# 이메일 브리핑 개선 계획 (2026-03-15)

> 근거: 프롬프트(`brief_instructions.j2`), 파싱(`brief_formatting.py`), 렌더링(`emailer.py`), 템플릿(`email.html.j2`) 코드 분석 + 실제 파이프라인 로그

---

## 1부: 포맷이 깨지는 구조적 원인

### 1.1 프롬프트 출력 ↔ 이메일 파싱 간 계약 불일치

프롬프트가 LLM에게 요구하는 소제목과, `brief_formatting.py`가 인식하는 라벨이 **부분적으로만 일치**합니다.

| 프롬프트가 요구하는 소제목 | `brief_formatting.py` 매핑 | 그룹 |
|---|---|---|
| 한줄 결론 | ✅ `CONCLUSION_LABELS` | conclusion |
| 핵심 수치 / 핵심 이슈 | ✅ `METRIC_LABELS` | metrics |
| 쉽게 보면 | ✅ `INSIGHT_LABELS` | insight |
| 왜 중요한지 | ✅ `INSIGHT_LABELS` | insight |
| 오늘 체크할 포인트 | ✅ `WATCH_LABELS` | watch |
| 주요 지표 | ✅ `METRIC_LABELS` | metrics |
| 거시 지표 (LAYER 3 내부 소제목) | ❌ 매핑 없음 | → metrics에 섞임 |

**문제**: LAYER 3의 `주요 지표` 블록 안에 `거시 지표`라는 하위 소제목이 있는데, 이건 `SECTION_KIND_BY_LABEL`에 없어서 일반 텍스트로 취급됩니다. `metrics` 그룹에 "거시 지표"라는 문자열이 bullet처럼 섞여 들어가고, `_build_stock_rows()`가 이걸 종목 행으로 파싱하려다 `PERCENT_RE` 매칭 실패로 `None` 반환 → 해당 행 소멸.

### 1.2 LAYER 2 뉴스 bullet 파싱의 취약점

프롬프트가 요구하는 형식:
```
- 헤드라인 | 시장 의미 | 한국 투자자 관점
```

`_parse_news_metric_line()`의 파싱:
```python
parts = [part.strip() for part in line.split("|")]
```

**깨지는 경우들**:
- 헤드라인에 `|`가 포함된 경우 (예: "S&P 500 | 나스닥 동반 하락") → 4-part split → 시장 의미가 잘림
- LLM이 `|` 대신 `—` 또는 `:` 를 쓰는 경우 → 1-part → 시장 의미/한국 투자자 관점 소멸
- LLM이 bullet 없이 문단으로 쓰는 경우 → `_first_metric_lines()`가 첫 3줄만 잘라서 불완전한 문장 반환

### 1.3 LAYER 3 종목 bullet 파싱의 취약점

프롬프트가 요구하는 형식:
```
- 애플은 AI 서비스 확대 기대감으로 2.3% 상승했습니다. [출처: Stooq]
```

`_build_stock_row()`의 파싱:
```python
parts = [part.strip() for part in line.split("|")]
percent_match = PERCENT_RE.search(normalized_line)
```

**깨지는 경우들**:
- 프롬프트는 `|` 구분이 아닌 자연어 문장을 요구하는데, 파서는 `|` split을 먼저 시도 → 자연어 문장에서 `|`가 없으면 1-part → `len(parts) >= 3` 분기 실패 → fallback 경로
- fallback에서 `_stock_name_from_line()`이 퍼센트 앞 텍스트를 종목명으로 추출하는데, "애플은 AI 서비스 확대 기대감으로"에서 `은` 조사 split → "애플" 추출은 성공
- 하지만 "TSMC(TSM)는"처럼 괄호가 있으면 `(은|는|이|가)\s*$` regex가 매칭 안 됨 → 종목명이 "TSMC(TSM)는 반도체 수요 회복 기대감으로" 전체가 됨

### 1.4 거시 지표 파싱의 한국어 조사 의존

```python
def _split_macro_line(line: str) -> tuple[str, str]:
    if "는 " in normalized_line:
        label, value = normalized_line.split("는 ", 1)
```

LLM이 "미국 10년물 금리는 4.28%로 올랐습니다"라고 쓰면 정상 동작하지만:
- "VIX 지수가 18.2로 하락했습니다" → `는 ` 없음, `은 ` 없음 → fallback `("거시 지표", 전체 문장)` → 라벨이 "거시 지표"로 통일되어 구분 불가
- "달러 인덱스(DXY)는 104.2입니다" → "달러 인덱스(DXY)" 추출 성공
- "공포탐욕지수는 32(공포)입니다" → "공포탐욕지수" 추출 성공

`가/이` 조사를 쓰는 경우만 깨집니다. 프롬프트에서 `은/는`을 강제하면 해결되지만, LLM 출력을 100% 통제할 수 없습니다.

---

## 2부: 내용 흐름에서 소멸되는 정보

### 소멸 맵

```
프롬프트 출력                    이메일 카드              상태
─────────────────────────────────────────────────────────────
LAYER 1 한줄 결론          →  핵심 요약 카드 1번째 줄    ✅ 표시
LAYER 1 핵심 수치          →  (없음)                    ❌ 소멸
LAYER 1 쉽게 보면          →  (없음)                    ❌ 소멸
  └ 코스피 영향 문장       →  (없음)                    ❌ 소멸
LAYER 1 오늘 체크할 포인트  →  (없음)                    ❌ 소멸

LAYER 2 한줄 결론          →  핵심 요약 카드 2번째 줄    ✅ 표시
LAYER 2 핵심 이슈          →  뉴스 카드 (bullet 파싱)    ⚠️ 부분 표시
  └ 시장 의미              →  뉴스 카드 서브텍스트       ⚠️ | 파싱 의존
  └ 한국 투자자 관점       →  뉴스 카드 서브텍스트       ⚠️ | 파싱 의존
LAYER 2 왜 중요한지        →  (없음)                    ❌ 소멸
LAYER 2 오늘 체크할 포인트  →  (없음)                    ❌ 소멸

LAYER 3 한줄 결론          →  핵심 요약 카드 3번째 줄    ✅ 표시
LAYER 3 주요 지표          →  시장 흐름 카드             ⚠️ 자연어 파싱 의존
LAYER 3 거시 지표          →  거시 지표 카드             ⚠️ 키워드 매칭 의존
LAYER 3 쉽게 보면          →  (없음)                    ❌ 소멸
LAYER 3 오늘 체크할 포인트  →  (없음)                    ❌ 소멸

참고 출처                  →  데이터 출처 카드           ✅ 표시
데이터 처리 메모           →  거시 지표 카드 하단        ✅ 표시
```

**소멸률**: 프롬프트가 생성하는 15개 블록 중 7개(47%)가 이메일에서 완전히 소멸.

---

## 3부: 상세 개선 계획

### Phase 1 — 파싱 안정화 (포맷 깨짐 수정)

#### 1-1. `거시 지표` 소제목을 `METRIC_LABELS`에 추가하되 별도 키로 분리

**파일**: `brief_formatting.py`

현재 LAYER 3의 `주요 지표` 블록 안에 `거시 지표`라는 하위 소제목이 있는데 인식 안 됨.

**변경**:
- `_SectionGroupState`에 `"macro"` 키 추가
- `MACRO_LABELS = {"거시 지표", "거시 환경"}`
- `SECTION_KIND_BY_LABEL`에 `{label: "macro" for label in MACRO_LABELS}` 추가
- `split_section_groups()` 반환값에 `"macro"` 그룹 포함

**영향**: `emailer.py`의 `_build_macro_rows()`가 `section.groups["macro"]`에서 직접 추출 가능 → 키워드 매칭 fallback 불필요

#### 1-2. 뉴스 bullet 파싱에 `|` 외 구분자 지원

**파일**: `emailer.py` — `_parse_news_metric_line()`

**변경**:
```python
# 현재: line.split("|") 만 사용
# 개선: | 가 1개 이하면 — 또는 : 로 재시도
parts = [part.strip() for part in line.split("|")]
if len(parts) < 2:
    parts = [part.strip() for part in re.split(r"\s*[—–]\s*", line)]
```

#### 1-3. 종목명 추출 regex 개선

**파일**: `emailer.py` — `_stock_name_from_line()`

**변경**:
```python
# 현재: re.split(r"(은|는|이|가)\s*$", prefix)
# 문제: "TSMC(TSM)는" → 괄호 뒤 조사 매칭 실패
# 개선: 조사 앞에 괄호/공백 허용
cleaned = re.split(r"(?:\([^)]*\))?\s*(은|는|이|가)\s", prefix)[0].strip()
```

#### 1-4. 거시 지표 라벨 추출에 `가/이` 조사 추가

**파일**: `emailer.py` — `_split_macro_line()`

**변경**:
```python
# 현재: "는 ", "은 " 만 체크
# 추가: "가 ", "이 " 도 체크
for particle in ("는 ", "은 ", "가 ", "이 "):
    if particle in normalized_line:
        label, value = normalized_line.split(particle, 1)
        return label.strip() or "거시 지표", value.strip() or normalized_line
return "거시 지표", normalized_line
```

---

### Phase 2 — 소멸 정보 복원 (내용 흐름 개선)

#### 2-1. 핵심 요약 카드에 LAYER 1 핵심 수치 추가

**파일**: `emailer.py` — `_build_email_context()`, `email.html.j2`

**변경**:
- `_build_email_context()`에서 LAYER 1의 `metrics` 그룹 첫 3줄을 `key_metrics` 리스트로 추출
- `email.html.j2`의 핵심 요약 카드에 `top_summary_lines` 아래 `key_metrics` bullet 렌더링
- 스타일: 15px, `#334155`, `font-variant-numeric: tabular-nums` (숫자 정렬)

**결과**: 원/달러 환율, 나스닥 선물, 공포탐욕지수가 이메일 최상단에 표시

#### 2-2. 핵심 요약 카드에 "코스피 영향" 한 줄 추가

**파일**: `emailer.py` — `_build_email_context()`

**변경**:
- LAYER 1의 `insight` 그룹에서 "코스피" 키워드가 포함된 첫 문장을 `kospi_impact` 변수로 추출
- `email.html.j2`에서 `key_metrics` 아래에 배경색 `#f0fdf4` 박스로 렌더링

#### 2-3. 뉴스 카드에 "왜 중요한지" 요약 추가

**파일**: `emailer.py` — `_build_news_items()` 또는 `_build_email_context()`

**변경**:
- LAYER 2의 `insight` 그룹 첫 문단을 `news_context` 변수로 추출
- `email.html.j2`의 뉴스 카드 상단(뉴스 bullet 위)에 13px italic 텍스트로 렌더링

#### 2-4. "오늘 체크할 포인트" 카드 신설

**파일**: `emailer.py` — `_build_email_context()`, `email.html.j2`

**변경**:
- 각 레이어의 `watch` 그룹에서 bullet을 수집 → `watch_items` 리스트 (최대 4~5개)
- `email.html.j2`에 거시 지표 카드와 출처 카드 사이에 새 카드 추가
- 아이콘: 🎯, 라벨 색상: `#7c3aed` (보라)

**결과**: 독자가 "오늘 뭘 봐야 하는지" 액션 아이템을 한눈에 확인

#### 2-5. 핵심 요약 카드에 레이어 라벨 추가

**파일**: `email.html.j2`

현재 `top_summary_lines` 3줄이 맥락 없이 나열됨.

**변경**:
```html
{% for line in top_summary_lines %}
<div style="...">
  <span style="color:#64748b;font-size:11px;font-weight:700;">
    {% if loop.index == 1 %}시장 판단{% elif loop.index == 2 %}뉴스{% else %}종목{% endif %}
  </span>
  <div style="...">{{ line }}</div>
</div>
{% endfor %}
```

---

### Phase 3 — 에지케이스 방어

#### 3-1. 뉴스 0건 시 빈 카드 대신 안내 메시지

**파일**: `emailer.py` — `_build_email_context()`

**변경**:
- `news_items`가 비어있고 `news_fallback_text`도 비어있으면, `news_fallback_text`에 기본 메시지 설정:
  `"주말/휴일로 주요 뉴스 업데이트가 없습니다. 다음 거래일 브리핑에서 확인해 주십시오."`
- `data_quality == "critical"`이면 notice 카드에도 반영

#### 3-2. `List-Unsubscribe` 헤더 추가

**파일**: `emailer.py` — `build_briefing_message()`

**변경**:
```python
msg["List-Unsubscribe"] = f"<{_unsubscribe_url(sender)}>"
msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
```

#### 3-3. 다크모드 색상 대비 보강

**파일**: `email.html.j2`

**변경**:
- 퍼센트 하락 빨강: `#dc2626` → `#f87171` (다크모드에서만)
- muted 텍스트: `#94a3b8` → `#cbd5e1` (다크모드에서만)

```css
@media (prefers-color-scheme: dark) {
  .pct-down { color: #f87171 !important; }
  .text-muted { color: #cbd5e1 !important; }
}
```

---

### Phase 4 — 프롬프트-파서 계약 강화

#### 4-1. 프롬프트에 파서 친화적 제약 추가

**파일**: `brief_instructions.j2`

**변경** (output_contract에 추가):
```
- LAYER 2 `핵심 이슈` bullet의 `|` 구분자는 반드시 3개 필드(헤드라인 | 시장 의미 | 한국 투자자 관점)로 유지한다. 헤드라인 안에 `|` 문자를 쓰지 않는다.
- LAYER 3 `주요 지표` bullet에서 종목명 뒤에는 반드시 `은/는` 조사를 사용한다.
- LAYER 3 `거시 지표` 소제목은 반드시 별도 줄에 단독으로 쓴다.
```

#### 4-2. 파싱 실패 시 fallback을 raw 텍스트로

**파일**: `emailer.py`

현재 파싱 실패 시 해당 블록이 소멸됨. 개선:
- `_build_news_items()`가 0건이면 LAYER 2 전체 텍스트를 `news_fallback_text`로 설정
- `_build_stock_rows()`가 0건이면 LAYER 3 전체 텍스트를 `stock_fallback_text`로 설정

이미 fallback 변수가 있지만, 현재는 `_fallback_section_text()`가 `section.content` 전체를 반환 → 이건 소제목 포함 raw 텍스트라 가독성이 떨어짐. 소제목을 제거하고 본문만 반환하도록 개선.

---

## 4부: 구현 우선순위

| 순서 | 작업 | Phase | 난이도 | 영향도 |
|------|------|-------|--------|--------|
| 1 | 뉴스 0건 시 안내 메시지 (3-1) | 3 | 낮음 | 높음 |
| 2 | 핵심 수치 카드 추가 (2-1) | 2 | 중간 | 높음 |
| 3 | 코스피 영향 한 줄 (2-2) | 2 | 낮음 | 높음 |
| 4 | 오늘 체크할 포인트 카드 (2-4) | 2 | 중간 | 높음 |
| 5 | 거시 지표 소제목 인식 (1-1) | 1 | 낮음 | 중간 |
| 6 | 뉴스 bullet 파싱 개선 (1-2) | 1 | 낮음 | 중간 |
| 7 | 종목명 추출 개선 (1-3) | 1 | 낮음 | 중간 |
| 8 | 거시 라벨 조사 추가 (1-4) | 1 | 낮음 | 낮음 |
| 9 | 핵심 요약 레이어 라벨 (2-5) | 2 | 낮음 | 중간 |
| 10 | 뉴스 "왜 중요한지" (2-3) | 2 | 낮음 | 중간 |
| 11 | 프롬프트 계약 강화 (4-1) | 4 | 낮음 | 중간 |
| 12 | 파싱 실패 fallback (4-2) | 4 | 중간 | 중간 |
| 13 | List-Unsubscribe 헤더 (3-2) | 3 | 낮음 | 낮음 |
| 14 | 다크모드 색상 보강 (3-3) | 3 | 낮음 | 낮음 |

---

## 5부: 개선 전후 이메일 구조 비교

### Before (현재)

```
┌─────────────────────────────┐
│ Morning Market Brief        │
│ 2026년 3월 15일 일요일      │
├─────────────────────────────┤
│ [데이터 품질 알림] (있을 때) │
├─────────────────────────────┤
│ 오늘 핵심 요약              │
│  "오늘은 리스크 주의..."    │  ← 26px, 맥락 없음
│  "연준 발언이..."           │  ← 17px, 맥락 없음
│  "반도체가 시장을..."       │  ← 17px, 맥락 없음
├─────────────────────────────┤
│ 📰 주요 뉴스               │
│  헤드라인                   │
│  시장 의미: ...             │
│  국내 투자자 관점: ...      │
│  ─────────                  │
│  (반복)                     │
├─────────────────────────────┤
│ 📊 시장 흐름               │
│  종목 bullet (파싱 의존)    │
├─────────────────────────────┤
│ 🔢 거시 지표               │
│  라벨 | 값 (조사 파싱 의존) │
├─────────────────────────────┤
│ 📎 데이터 출처              │
│  뉴스 / 시장 데이터         │
├─────────────────────────────┤
│ 면책 · 구독해지 · GitHub    │
└─────────────────────────────┘
```

### After (개선 후)

```
┌─────────────────────────────┐
│ Morning Market Brief        │
│ 2026년 3월 15일 일요일      │
├─────────────────────────────┤
│ [데이터 품질 알림] (있을 때) │
├─────────────────────────────┤
│ 오늘 핵심 요약              │
│  시장 판단                  │  ← 라벨 추가
│  "오늘은 리스크 주의..."    │
│  뉴스                       │
│  "연준 발언이..."           │
│  종목                       │
│  "반도체가 시장을..."       │
│ ─────────                   │
│  · 원/달러 1,342원 (+0.3%)  │  ← 핵심 수치 추가
│  · 나스닥 선물 약보합       │
│  · 공포탐욕 32 (공포)       │
│ ─────────                   │
│  🇰🇷 코스피 영향: ...       │  ← 코스피 영향 추가
├─────────────────────────────┤
│ 📰 주요 뉴스               │
│  "금리·달러 흐름이 겹치며"  │  ← 왜 중요한지 추가
│  ─────────                  │
│  헤드라인                   │
│  시장 의미: ...             │
│  국내 투자자 관점: ...      │
│  (반복)                     │
│  ─────────                  │
│  (뉴스 0건 시 안내 메시지)  │  ← 빈 카드 방지
├─────────────────────────────┤
│ 📊 시장 흐름               │
│  종목 bullet                │
├─────────────────────────────┤
│ 🔢 거시 지표               │
│  라벨 | 값                  │
├─────────────────────────────┤
│ 🎯 오늘 체크할 포인트       │  ← 신규 카드
│  · FOMC 의사록 공개 주시    │
│  · 엔비디아 GTC 컨퍼런스    │
│  · BTC ETF 자금 흐름        │
├─────────────────────────────┤
│ 📎 데이터 출처              │
├─────────────────────────────┤
│ 면책 · 구독해지 · GitHub    │
└─────────────────────────────┘
```

### 핵심 차이

1. **핵심 수치 3개**가 최상단에 노출 → 아침에 숫자만 보고 싶은 독자 충족
2. **코스피 영향** 한 줄이 보임 → 한국 투자자 핵심 관심사
3. **레이어 라벨**로 3줄 요약의 맥락 제공
4. **"왜 중요한지"**로 뉴스 묶음의 공통 맥락 제공
5. **오늘 체크할 포인트** 카드로 액션 아이템 제공
6. **뉴스 0건 안내**로 빈 카드 방지

---

## 6부: 2026 금융 뉴스레터 트렌드 기반 루브릭 검증

> 근거: Brew Markets (Morning Brew 금융 뉴스레터), Finimize Daily Brief, Designmodo 2026 이메일 디자인 트렌드 리포트, 2026 이메일 마케팅 베스트 프랙티스 조사

### 업계 사례 분석

#### Brew Markets (Morning Brew 금융 뉴스레터) — 2026.03.13 실제 이슈

구조:
```
1. MARKETS — 지수 테이블 (Nasdaq/S&P/Dow/10-Year/Bitcoin/Oil + 등락률)
2. INVESTING — 메인 스토리 (긴 내러티브 + "Zoom out" 맥락)
3. STOCKS — 🟢 What's up / 🔴 What's down (종목별 1줄 bullet)
4. WARNING OF THE DAY — 경고/심층 분석 스토리
5. TECH TROUBLES — 테크 섹터 심층 분석
6. NEWS — Around the market (bullet 뉴스 모음)
7. CALENDAR — 다음 주 일정 (요일별)
8. RECS — 추천 읽을거리
9. SHARE THE BREW — 리퍼럴 프로그램
```

핵심 패턴:
- **숫자 테이블이 최상단** — 지수 6개를 이름/값/등락률 3열 테이블로 즉시 노출
- **"Bottom line"으로 마무리** — 각 심층 기사 끝에 한 줄 결론
- **"Zoom out"으로 맥락 제공** — 단기 뉴스를 장기 트렌드에 연결
- **What's up / What's down 분리** — 종목을 상승/하락으로 명확히 구분
- **CALENDAR 섹션** — "오늘 뭘 봐야 하는지" 액션 아이템 제공

#### Finimize Daily Brief — 100만+ 구독자

슬로건: "Get smarter in 3 minutes a day"
구조: 매일 2개 핵심 토픽 × (What happened → Why it matters → The bottom line)

핵심 패턴:
- **3분 읽기** — 극도로 압축된 분량
- **"What happened → Why it matters"** — 사실과 해석을 명확히 분리
- **전문 용어 없음** — "No jargon, no bias"

#### 2026 이메일 디자인 트렌드 (Designmodo 리포트)

주요 트렌드:
1. **Mobile-First 싱글 컬럼** — 가장 안정적인 구조
2. **"Above the Fold" 접근** — 핵심 정보를 최상단에 배치, 첫 몇 초 안에 결정
3. **"Cut to the Chase" 철학** — 직접적이고 간결하게, 스토리텔링보다 핵심 메시지 우선
4. **다크모드 최적화** — 필수 요소로 자리잡음
5. **Digest 포맷** — 4~5개 콘텐츠 블록, 충분한 여백, 시각과 텍스트 균형
6. **구독 해지 링크 강조** — 숨기지 않고 명확하게 표시 (Gmail 스팸 방지)
7. **접근성** — 시맨틱 HTML, alt 텍스트, 스크린 리더 호환

### 루브릭 검증 — 현재 템플릿 vs 업계 기준

| 루브릭 항목 | 업계 기준 | 현재 상태 | 개선 계획 반영 | 판정 |
|---|---|---|---|---|
| **숫자 최상단 노출** | Brew Markets: 6개 지수 테이블이 첫 화면 | ❌ 한줄 결론만 노출, 핵심 수치 없음 | ✅ Phase 2-1: 핵심 수치 3개 추가 | 개선 필요 |
| **사실/해석 분리** | Finimize: What happened / Why it matters | ⚠️ 뉴스 카드에 시장 의미/한국 투자자 관점 분리는 있으나, "왜 중요한지" 소멸 | ✅ Phase 2-3: "왜 중요한지" 복원 | 부분 충족 |
| **액션 아이템** | Brew Markets: CALENDAR 섹션, Finimize: "The bottom line" | ❌ "오늘 체크할 포인트" 전부 소멸 | ✅ Phase 2-4: 체크포인트 카드 신설 | 개선 필요 |
| **Bottom line 결론** | Brew Markets/Finimize 모두 사용 | ⚠️ 핵심 요약 3줄은 있으나 맥락 라벨 없음 | ✅ Phase 2-5: 레이어 라벨 추가 | 부분 충족 |
| **Mobile-First 싱글 컬럼** | 2026 필수 | ✅ 카드 기반 싱글 컬럼 | — | 충족 |
| **Above the Fold** | 핵심 정보 최상단 | ⚠️ 한줄 결론은 있으나 숫자 없음 | ✅ Phase 2-1, 2-2 | 부분 충족 |
| **다크모드** | 2026 필수 | ✅ prefers-color-scheme 대응 | ⚠️ Phase 3-3: 색상 대비 보강 필요 | 대체로 충족 |
| **Digest 포맷 (4~5 블록)** | 간결한 블록 구성 | ✅ 5개 카드 (요약/뉴스/시장/거시/출처) | ✅ 6개로 확장 (체크포인트 추가) | 충족 |
| **구독 해지 명확성** | Gmail 정책상 필수 | ⚠️ mailto: 링크만 있음, List-Unsubscribe 헤더 없음 | ✅ Phase 3-2 | 개선 필요 |
| **빈 상태 처리** | 뉴스 없을 때 안내 | ❌ 뉴스 0건 시 섹션 소멸 | ✅ Phase 3-1 | 개선 필요 |
| **읽기 시간 3~5분** | Finimize 3분, Brew Markets 5분 | ⚠️ 프롬프트는 3~5분 목표이나 이메일에서 47% 소멸로 실제 2분 미만 | ✅ 소멸 정보 복원으로 3분 수준 회복 | 부분 충족 |
| **종목 상승/하락 구분** | Brew Markets: 🟢/🔴 분리 | ❌ 시장 흐름 카드에 혼재 | — (Phase 2 이후 고려) | 미충족 |
| **주간 캘린더/일정** | Brew Markets: CALENDAR 섹션 | ❌ 없음 | — (범위 외, 향후 고려) | 미충족 |

### 검증 결과 요약

**14개 루브릭 중:**
- ✅ 충족: 3개 (싱글 컬럼, Digest 포맷, 다크모드 기본)
- ⚠️ 부분 충족: 5개 (사실/해석 분리, Bottom line, Above the Fold, 다크모드 대비, 읽기 시간)
- ❌ 미충족: 6개 (숫자 최상단, 액션 아이템, 구독 해지, 빈 상태, 종목 구분, 캘린더)

**개선 계획(Phase 1~4)이 반영되면:**
- ✅ 충족: 10개 (+7)
- ⚠️ 부분 충족: 2개 (종목 구분, 캘린더는 범위 외)
- ❌ 미충족: 2개

### 개선 계획에 추가 반영할 사항

**1) 종목 상승/하락 시각적 분리 (Brew Markets 패턴)**

현재 시장 흐름 카드에서 종목이 순서대로 나열되는데, Brew Markets처럼 🟢 상승 / 🔴 하락으로 그룹을 나누면 스캔 가능성이 크게 향상됩니다.

구현: `_build_stock_rows()`에서 `tone` 필드(up/down/flat)로 정렬 후, 템플릿에서 그룹 헤더 삽입.

**2) "Zoom out" 맥락 문장 (Brew Markets 패턴)**

Brew Markets의 "Zoom out"은 단기 뉴스를 장기 트렌드에 연결하는 1~2문장입니다. 이는 프롬프트의 "쉽게 보면"과 정확히 같은 역할인데, 현재 이메일에서 소멸됩니다. Phase 2-2의 코스피 영향 문장 복원이 이 역할을 부분적으로 대체합니다.

**3) preheader 텍스트 최적화**

현재 `top_summary_lines[:2]`를 140자로 잘라서 preheader로 사용하는데, Brew Markets는 제목에 핵심 키워드를 넣고 preheader에 보조 정보를 넣습니다. 핵심 수치(원/달러, 나스닥 방향)를 preheader에 포함하면 받은편지함에서 바로 숫자를 확인할 수 있습니다.
