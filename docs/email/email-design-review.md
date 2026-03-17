# 이메일 브리핑 디자인 및 구조 개선 조사

2026-03-17 작성. 현재 이메일 템플릿(`email.html.j2`)과 브리핑 프롬프트(`brief_instructions.j2`)를 분석하고, 업계 금융 뉴스레터(Morning Brew, Finimize, The Daily Upside 등) 베스트 프랙티스와 비교한 결과입니다.

---

## 1. 현재 이메일 구조

| 순서 | 카드 | 내용 |
|---|---|---|
| ① | 헤더 | "Morning Market Brief" + 날짜 |
| ② | 데이터 품질 알림 | (조건부) 데이터 누락 시 경고 |
| ③ | 핵심 요약 (히어로) | LAYER 1 한줄 판단 + 핵심 수치 + 코스피 영향 |
| ④ | 주요 뉴스 | LAYER 2 뉴스 헤드라인 + 시장 의미 + 한국 투자자 관점 |
| ⑤ | 시장 흐름 | LAYER 3 종목별 등락 (상승/하락 분리) |
| ⑥ | 거시 지표 | VIX, DXY, US10Y 등 + 데이터 처리 메모 |
| ⑦ | 체크포인트 | "오늘 체크할 포인트" 리스트 |
| ⑧ | 데이터 출처 | 뉴스 출처 + 시장 데이터 출처 |
| ⑨ | 면책/구독해지 | 면책 문구 + 구독 해지 + GitHub 링크 |

---

## 2. 잘 되어 있는 점

- **다크 모드 완전 지원**: `prefers-color-scheme: dark` 미디어 쿼리로 모든 카드/텍스트/색상 대응
- **모바일 반응형**: 600px 이하 breakpoint, 터치 타겟 44px 확보
- **카드 기반 레이아웃**: 섹션별 분리가 명확, 스캔하기 좋음
- **상승/하락 색상 분리**: `pct-up`(초록), `pct-down`(빨강) 시각적 구분
- **preheader 최적화**: 핵심 수치 3개를 preheader에 넣어 받은편지함 미리보기 활용
- **접근성**: `role="presentation"`, 시맨틱 구조, 충분한 색상 대비
- **Outlook 호환**: MSO 조건부 스타일 포함
- **한국어 폰트 스택**: Apple SD Gothic Neo → Noto Sans KR → Malgun Gothic

---

## 3. 개선이 필요한 부분

### 3-1. 시장 데이터 시각화 부재 🔴

**현재**: 거시 지표가 텍스트 테이블(라벨 + 값)로만 표시. 종목도 텍스트 한 줄.

**업계 표준**:
- Finimize: 주요 지수를 상단에 컬러 배지(🟢+2.1% / 🔴-0.8%)로 한눈에 표시
- Morning Brew: "Markets" 섹션에 지수별 등락을 컬러 코딩된 인라인 배지로 표시
- The Daily Upside: 핵심 수치를 볼드 + 컬러로 강조

**개선 방향**:
- 상단에 "시장 스냅샷" 미니 대시보드 추가: S&P 500, 나스닥, BTC, VIX를 컬러 배지로 한 줄 표시
- CSS 기반 프로그레스 바로 등락폭 시각화 (이메일에서 JS/SVG 불가하므로 `<td>` 배경색 + 너비 비율로 구현)
- 종목 카드에 등락률을 큰 숫자 + 컬러로 강조 (현재는 본문 텍스트에 묻혀 있음)

### 3-2. 뉴스 카드 구조 — "So What?" 부족 🔴

**현재**: 헤드라인 → 시장 의미 → 한국 투자자 관점이 있지만, 시각적으로 구분이 약함. 모두 같은 크기/색상의 텍스트.

**업계 표준**:
- Finimize: 각 뉴스를 "What happened → Why it matters → What now" 3단 구조로 시각적 분리
- Morning Brew: 헤드라인을 크게, 본문을 작게, "Bottom line" 을 볼드로 분리
- The Daily Upside: 각 스토리에 명확한 시각적 계층 (제목 → 요약 → 인사이트)

**개선 방향**:
- 뉴스 아이템별 3단 구조를 시각적으로 분리:
  - 헤드라인: 현재 20px → 유지
  - "시장 의미": 별도 배경색 박스 또는 왼쪽 보더 강조
  - "한국 투자자 관점": 🇰🇷 아이콘 + 다른 배경색으로 시각적 분리
- 각 뉴스에 "핵심 한줄" (TL;DR) 추가 — 프롬프트에서 생성

### 3-3. 인사이트/액션 아이템 강조 부족 🟡

**현재**: "오늘 체크할 포인트"가 ⑦번 카드로 하단에 위치. 읽기 전에 스크롤 아웃될 가능성.

**업계 표준**:
- Finimize: "What now" (액션 아이템)을 각 뉴스 바로 아래에 배치
- Morning Brew: 각 섹션 끝에 "Bottom line" 으로 즉시 인사이트 제공

**개선 방향**:
- 각 레이어(뉴스, 종목) 끝에 인라인으로 "체크 포인트" 배치
- 또는 히어로 카드 바로 아래에 "오늘의 액션" 카드를 별도로 올림
- 현재 ⑦번 위치는 너무 늦음

### 3-4. 시장 스냅샷 대시보드 없음 🟡

**현재**: 거시 지표가 ⑥번 카드(하단)에 텍스트 테이블로만 존재. 핵심 수치는 ③번 히어로에 bullet으로 있지만 시각적 임팩트 부족.

**업계 표준**:
- 대부분의 금융 뉴스레터가 상단에 주요 지수 스냅샷을 배치
- 컬러 코딩된 등락 표시가 기본

**개선 방향**:
- 헤더 카드 바로 아래 또는 히어로 카드 상단에 "시장 스냅샷" 1줄 추가:
  ```
  S&P 500 🟢+0.8%  |  나스닥 🟢+1.2%  |  BTC 🔴-2.1%  |  VIX 19.3
  ```
- 이메일 호환 방식: `<td>` 기반 인라인 배지, 배경색으로 상승/하락 표시

### 3-5. 읽기 시간 / 난이도 표시 없음 🟢

**업계 표준**:
- Finimize: "3 min read" 표시
- Morning Brew: 상단에 읽기 시간 암시

**개선 방향**:
- 헤더에 "📖 3분 읽기" 추가 (간단)

### 3-6. 섹션 네비게이션 없음 🟢

**현재**: 카드가 순서대로 나열될 뿐, 목차나 앵커 링크 없음.

**업계 표준**:
- Morning Brew: 상단에 "Today's Menu" 목차
- The Daily Upside: 상단에 섹션 링크

**개선 방향**:
- 헤더 카드에 "오늘 핵심 | 뉴스 | 종목 | 거시" 앵커 링크 추가
- 단, 이메일 클라이언트별 앵커 지원이 불균일하므로 우선순위 낮음

### 3-7. BTC ETF 데이터 전용 섹션 없음 🟡

**현재**: BTC ETF 보유량/순유입 데이터가 수집되지만 이메일에서 별도 섹션으로 표시되지 않음. LAYER 3 종목 브리핑에 텍스트로 섞여 있을 수 있음.

**개선 방향**:
- BTC 섹션을 별도 카드로 분리: BTC 가격 + Fear&Greed + ETF 유입/유출
- 비트코인 투자자에게 가장 관심 높은 데이터이므로 시각적 강조 가치 있음

### 3-8. 소셜 공유 / 포워딩 유도 없음 🟢

**업계 표준**:
- Morning Brew: 하단에 "Share with a friend" + 리퍼럴 프로그램
- Finimize: 소셜 공유 버튼

**개선 방향**:
- 하단에 "이 브리핑이 유용했다면 동료에게 공유해주세요" + mailto 링크
- 현재 규모에서는 우선순위 낮음

---

## 4. 프롬프트 ↔ 이메일 템플릿 간 갭

| 프롬프트가 생성하는 것 | 이메일 템플릿이 표시하는 것 | 갭 |
|---|---|---|
| LAYER 1 한줄 판단 + 핵심 수치 + 코스피 영향 | ✅ 히어로 카드에 모두 표시 | 없음 |
| LAYER 2 뉴스 (헤드라인 \| 시장 의미 \| 한국 투자자 관점) | ⚠️ 파싱은 하지만 시각적 분리 약함 | 3-2 참고 |
| LAYER 3 종목 (종목명 + 원인 + 등락률 + 출처) | ⚠️ 텍스트 한 줄로 표시, 등락률 강조 부족 | 3-1 참고 |
| 거시 지표 (VIX, DXY, US10Y 등) | ⚠️ 하단 텍스트 테이블, 상단 스냅샷 없음 | 3-4 참고 |
| 오늘 체크할 포인트 | ⚠️ 하단 ⑦번 카드, 위치가 너무 늦음 | 3-3 참고 |
| BTC ETF 보유량/순유입 | ❌ 별도 섹션 없음 | 3-7 참고 |
| 뉴스별 "왜 중요한지" | ⚠️ 있지만 시각적 강조 없음 | 3-2 참고 |

---

## 5. 우선순위 정리

| 순위 | 항목 | 영향도 | 난이도 | 설명 |
|---|---|---|---|---|
| 1 | 시장 스냅샷 대시보드 | 높음 | 중간 | 상단에 주요 지수 컬러 배지 추가. 첫인상 개선 |
| 2 | 뉴스 카드 시각적 계층 분리 | 높음 | 중간 | 헤드라인/시장의미/한국관점을 배경색+보더로 분리 |
| 3 | 종목 등락률 시각적 강조 | 중간 | 낮음 | 등락률을 큰 숫자+컬러 배지로 표시 |
| 4 | 체크포인트 위치 상향 | 중간 | 낮음 | 각 레이어 끝 또는 히어로 바로 아래로 이동 |
| 5 | BTC 전용 섹션 | 중간 | 중간 | BTC 가격+Fear&Greed+ETF 유입을 별도 카드로 |
| 6 | 읽기 시간 표시 | 낮음 | 낮음 | 헤더에 "📖 3분" 추가 |
| 7 | 섹션 네비게이션 | 낮음 | 중간 | 이메일 앵커 호환성 이슈로 후순위 |
| 8 | 소셜 공유 유도 | 낮음 | 낮음 | 현재 규모에서는 불필요 |

---

---

## 6. 이모지 제거 — HTML/CSS 대체 방안

현재 템플릿에서 이모지를 섹션 라벨에 사용 중:
- `📰 주요 뉴스와 시장 의미`
- `📊 시장 흐름`
- `🔢 거시 지표`
- `🎯 오늘 체크할 포인트`
- `📎 데이터 출처`
- `🇰🇷` 코스피 영향
- `🟢 상승` / `🔴 하락·보합`

### 이모지의 문제점
- 이메일 클라이언트마다 렌더링이 다름 (Gmail vs Outlook vs Apple Mail)
- 전문적인 금융 브리핑 톤과 맞지 않음
- 다크 모드에서 일부 이모지가 깨지거나 배경과 충돌

### 대체 방법: HTML 엔티티 + CSS 인라인 스타일

**상승/하락 인디케이터** — 이모지 🟢🔴 대신:

```html
<!-- 상승 -->
<span style="color:#16a34a;font-size:11px;">&#9650;</span>  <!-- ▲ 삼각형 -->
<span style="color:#16a34a;font-size:11px;">&#9652;</span>  <!-- ▴ 작은 삼각형 -->

<!-- 하락 -->
<span style="color:#dc2626;font-size:11px;">&#9660;</span>  <!-- ▼ 삼각형 -->
<span style="color:#dc2626;font-size:11px;">&#9662;</span>  <!-- ▾ 작은 삼각형 -->

<!-- 보합 -->
<span style="color:#6b7280;font-size:9px;">&#9644;</span>   <!-- ▬ 가로 바 -->
<span style="color:#6b7280;">&#8212;</span>                 <!-- — em dash -->
```

**섹션 라벨** — 이모지 대신 CSS 인라인 도형:

```html
<!-- 컬러 도트 (● U+25CF) -->
<span style="color:#1e40af;font-size:8px;vertical-align:middle;">&#9679;</span> 주요 뉴스

<!-- 왼쪽 보더 액센트 (이모지 완전 제거) -->
<td style="border-left:3px solid #1e40af;padding-left:12px;">주요 뉴스와 시장 의미</td>

<!-- 작은 사각형 (■ U+25A0) -->
<span style="color:#0f766e;font-size:7px;vertical-align:middle;">&#9632;</span> 시장 흐름
```

**코스피 영향** — 🇰🇷 대신:

```html
<!-- 텍스트 라벨 -->
<span style="color:#166534;font-size:12px;font-weight:700;letter-spacing:0.05em;">KR</span>

<!-- 또는 보더 박스 -->
<span style="display:inline-block;border:1px solid #166534;border-radius:3px;padding:1px 5px;color:#166534;font-size:11px;font-weight:700;">KR</span>
```

### 이메일 클라이언트 호환성

| 방법 | Gmail | Outlook | Apple Mail | 다크 모드 |
|---|---|---|---|---|
| HTML 엔티티 (▲▼●■) | ✅ | ✅ | ✅ | ✅ (color 속성 따름) |
| CSS border-left 액센트 | ✅ | ✅ | ✅ | ✅ |
| CSS ::before 가상 요소 | ✅ | ❌ | ✅ | ✅ |
| SVG 인라인 | ✅ | ❌ | ✅ | ⚠️ |
| 이모지 | ⚠️ 렌더링 차이 | ⚠️ 깨짐 가능 | ✅ | ⚠️ |

**결론**: HTML 엔티티(▲▼●■) + CSS 인라인 color가 가장 안전. 모든 이메일 클라이언트에서 동일하게 렌더링되고 다크 모드에서도 color 속성을 따름.

---

## 7. 헤더 디자인 — 2026 트렌드 방향

### 현재 헤더
```
┌─────────────────────────────────┐
│ Morning Market Brief            │  ← 20px, 700 weight
│ 2026년 3월 17일 (월)            │  ← 14px, 회색
│ ─────────────────────────────── │
└─────────────────────────────────┘
```
문제: 평범한 카드 + 텍스트. 브랜드 아이덴티티 없음. 2020년대 초반 스타일.

### 2026 트렌드 키워드
- **Monochromatic / Duotone**: 단색 또는 2색 조합으로 세련된 인상
- **Gradient accent**: 미묘한 그라디언트를 헤더 상단/하단 보더에 적용
- **Typography-first**: 로고 이미지 없이 타이포그래피만으로 브랜드 표현
- **Negative space**: 여백을 넉넉히 써서 고급스러운 느낌
- **Subtle depth**: 그림자 최소화, 대신 배경색 레이어로 깊이감

### 제안: 미니멀 그라디언트 헤더

```
┌─────────────────────────────────┐
│                                 │
│  M                              │  ← 단일 이니셜, 48px, 800 weight
│  Morning Market Brief           │  ← 16px, 600 weight, letter-spacing 0.08em
│  2026. 03. 17 Mon               │  ← 13px, 400 weight, 뮤트 컬러
│                                 │
│ ═══════════════════════════════ │  ← 2px gradient border (slate→blue→slate)
└─────────────────────────────────┘
```

HTML 구현 예시:
```html
<td style="padding:32px 24px 20px 24px;">
  <!-- 이니셜 마크 -->
  <div style="font-family:'SF Pro Display','Apple SD Gothic Neo',sans-serif;
              color:#0f172a;font-size:48px;font-weight:800;
              letter-spacing:-0.04em;line-height:1;">M</div>
  <!-- 브랜드명 -->
  <div style="padding-top:8px;font-family:'SF Pro Display','Apple SD Gothic Neo',sans-serif;
              color:#334155;font-size:15px;font-weight:600;
              letter-spacing:0.08em;text-transform:uppercase;">Morning Market Brief</div>
  <!-- 날짜 -->
  <div style="padding-top:6px;font-family:'SF Pro Text','Apple SD Gothic Neo',sans-serif;
              color:#94a3b8;font-size:13px;font-weight:400;">2026. 03. 17 Mon</div>
  <!-- 그라디언트 구분선 -->
  <div style="margin-top:20px;height:2px;
              background:linear-gradient(90deg,#cbd5e1,#3b82f6,#cbd5e1);
              border-radius:1px;"></div>
</td>
```

### 대안 스타일들

**A. 다크 헤더 (프리미엄 금융 느낌)**
```html
<td style="background:#0f172a;padding:28px 24px;border-radius:16px 16px 0 0;">
  <div style="color:#f8fafc;font-size:14px;font-weight:600;
              letter-spacing:0.1em;text-transform:uppercase;">Morning Market Brief</div>
  <div style="padding-top:6px;color:#64748b;font-size:13px;">2026. 03. 17 Mon</div>
</td>
```

**B. 사이드 액센트 (좌측 컬러 바)**
```html
<td style="border-left:4px solid #1e40af;padding:24px 24px 20px 20px;">
  <div style="color:#0f172a;font-size:15px;font-weight:700;
              letter-spacing:0.06em;">MORNING MARKET BRIEF</div>
  <div style="padding-top:4px;color:#94a3b8;font-size:13px;">2026. 03. 17</div>
</td>
```

**C. 미니멀 라인 (극도로 절제)**
```html
<td style="padding:24px 24px 16px 24px;">
  <div style="color:#0f172a;font-size:13px;font-weight:700;
              letter-spacing:0.12em;text-transform:uppercase;">Morning Market Brief</div>
  <div style="margin-top:12px;height:1px;background:#e2e8f0;"></div>
</td>
```

### 호환성 참고
- `linear-gradient`: Gmail ✅, Apple Mail ✅, Outlook ❌ (fallback으로 solid color 필요)
- `border-radius`: Gmail ✅, Apple Mail ✅, Outlook ❌ (MSO 조건부 스타일로 대응)
- `letter-spacing`, `text-transform`: 모든 클라이언트 ✅

---

## 8. 컬러 배지 통일 — 상승/하락 시스템

현재 문제: 상승/하락 표시가 섹션마다 다름
- 히어로: 텍스트에 `pct-up`/`pct-down` 클래스
- 시장 흐름: `🟢 상승` / `🔴 하락·보합` 이모지 라벨
- 거시 지표: 텍스트만

### 통일된 배지 시스템 제안

```html
<!-- 상승 배지 -->
<span style="display:inline-block;background:#dcfce7;color:#166534;
             padding:2px 8px;border-radius:4px;font-size:13px;
             font-weight:700;font-variant-numeric:tabular-nums;">
  &#9650; +1.23%
</span>

<!-- 하락 배지 -->
<span style="display:inline-block;background:#fef2f2;color:#991b1b;
             padding:2px 8px;border-radius:4px;font-size:13px;
             font-weight:700;font-variant-numeric:tabular-nums;">
  &#9660; -0.87%
</span>

<!-- 보합 배지 -->
<span style="display:inline-block;background:#f3f4f6;color:#4b5563;
             padding:2px 8px;border-radius:4px;font-size:13px;
             font-weight:700;font-variant-numeric:tabular-nums;">
  &#8212; 0.00%
</span>
```

다크 모드 대응:
```css
@media (prefers-color-scheme: dark) {
  .badge-up { background: #14532d !important; color: #4ade80 !important; }
  .badge-down { background: #450a0a !important; color: #fca5a5 !important; }
  .badge-flat { background: #1f2937 !important; color: #9ca3af !important; }
}
```

이 배지를 히어로, 시장 흐름, 거시 지표, 시장 스냅샷 모든 곳에서 동일하게 사용하면 시각적 일관성이 확보됩니다.

---

## 9. 참고한 업계 뉴스레터 및 트렌드

| 뉴스레터 | 특징 | 참고할 점 |
|---|---|---|
| **Morning Brew** | 위트 있는 톤, 상단 목차, 섹션별 명확한 분리 | 목차 구조, "Bottom line" 패턴 |
| **Finimize** | "3분 읽기", What/Why/What now 3단 구조, 깔끔한 데이터 시각화 | 뉴스 3단 구조, 읽기 시간 표시 |
| **The Daily Upside** | 심층 분석 중심, 명확한 시각적 계층, 깔끔한 타이포그래피 | 헤드라인 계층 구조 |
| **CFO Brew** | 금융 전문가 대상, 데이터 중심, 간결한 포맷 | 전문가 톤 유지하면서 접근성 확보 |

| 2026 디자인 트렌드 | 이메일 적용 가능성 |
|---|---|
| Monochromatic / Duotone 컬러 | ✅ 높음 — 단색 계열로 세련된 인상 |
| Typography-first 브랜딩 | ✅ 높음 — 이미지 없이 폰트만으로 브랜드 표현 |
| Gradient accent | ⚠️ 중간 — Gmail/Apple OK, Outlook fallback 필요 |
| Glassmorphism | ❌ 낮음 — backdrop-filter 이메일 미지원 |
| Neumorphism | ❌ 낮음 — box-shadow 복합 사용 이메일 호환성 낮음 |
| Negative space 활용 | ✅ 높음 — padding/margin만으로 구현 가능 |

---

## 10. 중복 제거 및 구조 최적화

### 10-1. "LAYER 1 | 오늘 한줄 판단" — 불필요 문구 제거

현재 LAYER 1 소제목 4개: `한줄 결론`, `핵심 수치`, `쉽게 보면`, `오늘 체크할 포인트`

| 소제목 | 문제 | 제안 |
|---|---|---|
| `한줄 결론` | "오늘은 매수 관심 국면입니다" 같은 고정 문구가 투자 권유처럼 보일 수 있음 | 유지하되 문구를 "시장 분위기: 관심 / 관망 / 주의"로 톤 다운 |
| `핵심 수치` | ✅ 유지 | 그대로 |
| `쉽게 보면` | "코스피에 미치는 영향" 문장이 LAYER 2, LAYER 3의 "한국 투자자 관점"과 중복 | **제거**. 코스피 영향은 LAYER 1 핵심 수치 마지막 bullet에 한 줄로 통합 |
| `오늘 체크할 포인트` | LAYER 2, LAYER 3에도 각각 "오늘 체크할 포인트"가 있어 3번 반복 | **LAYER 1에서만 유지**, LAYER 2/3에서는 제거 |

### 10-2. 전체 "오늘 체크할 포인트" 중복

현재: 3개 레이어 모두에 `오늘 체크할 포인트`가 있음 → 최대 6개 bullet이 분산

| 위치 | 현재 | 제안 |
|---|---|---|
| LAYER 1 | 1~2개 | **유지** — 전체 시장 관점 체크포인트 |
| LAYER 2 | 1~2개 | **제거** — 뉴스별 인사이트는 각 bullet의 "시장 의미"로 충분 |
| LAYER 3 | 1~2개 | **제거** — 종목별 인사이트는 각 bullet의 원인 설명으로 충분 |
| 이메일 ⑦ 체크포인트 카드 | 별도 카드 | **제거** — LAYER 1의 체크포인트가 히어로 카드에 이미 표시됨 |

### 10-3. "한줄 결론" 중복

현재: 3개 레이어 모두 `한줄 결론` 소제목이 있음

| 위치 | 현재 | 제안 |
|---|---|---|
| LAYER 1 한줄 결론 | 시장 판단 | **유지** — 히어로 카드의 핵심 |
| LAYER 2 한줄 결론 | 뉴스 요약 | **제거** — 뉴스 카드 상단에 1줄 리드 문장으로 대체 (소제목 없이) |
| LAYER 3 한줄 결론 | 종목 요약 | **제거** — 시장 흐름 카드 상단에 1줄 리드 문장으로 대체 |

### 10-4. "쉽게 보면" / "왜 중요한지" 중복

| 위치 | 현재 | 제안 |
|---|---|---|
| LAYER 1 `쉽게 보면` | 코스피 영향 | **제거** — 핵심 수치에 통합 |
| LAYER 2 `왜 중요한지` | 뉴스 흐름 묶음 | **유지** — 뉴스 간 연결 설명은 가치 있음 |
| LAYER 3 `쉽게 보면` | 종목 공통 해석 | **제거** — LAYER 1 판단과 중복 |

### 10-5. 최적화 후 구조

```
LAYER 1 | 시장 판단
  - 한줄 결론 (시장 분위기 + 근거 1문장)
  - 핵심 수치 (3개 bullet + 코스피 영향 1줄)
  - 오늘 체크할 포인트 (2~3개 bullet, 전체 통합)

LAYER 2 | 주요 뉴스
  - (리드 문장 1줄, 소제목 없이)
  - 핵심 이슈 3~5개 (헤드라인 | 시장 의미 | 한국 투자자 관점)
  - 왜 중요한지 (뉴스 간 연결 2문장)

LAYER 3 | 종목 브리핑
  - (리드 문장 1줄, 소제목 없이)
  - 종목 4~6개 + 거시 지표 2~4개
```

제거 항목 요약:
- `쉽게 보면` 소제목 2개 (LAYER 1, 3)
- `오늘 체크할 포인트` 2개 (LAYER 2, 3)
- `한줄 결론` 소제목 2개 (LAYER 2, 3 — 내용은 리드 문장으로 유지)
- 이메일 ⑦ 체크포인트 카드 (LAYER 1 히어로에 통합)

---

## 11. 데이터 출처 섹션 심플화

### 현재 구조 (⑧ 데이터 출처 카드)

```
📎 데이터 출처
  뉴스
    · 헤드라인1                    Reuters
    · 헤드라인2                    Bloomberg
    · 헤드라인3                    CoinDesk
  시장 데이터
    · 거시 지표: FRED, yfinance
    · 미국 지수/기술주: Stooq
    · 비트코인: CoinGecko
    · X 시그널: Grok
```

문제:
- 뉴스 출처를 헤드라인별로 나열 → 뉴스 카드에서 이미 출처가 보이므로 중복
- 시장 데이터 출처는 매일 동일 → 동적으로 빌드할 필요 없음
- 카드 자체가 너무 큼

### 제안: 1줄 하드코딩 footer

시장 데이터 소스는 코드에서 고정(`_market_source_lines()`가 이미 하드코딩):

```python
def _market_source_lines() -> list[str]:
    return [
        "거시 지표: FRED, yfinance",
        "미국 지수/기술주: Stooq",
        "비트코인: CoinGecko",
        "X 시그널: Grok",
    ]
```

이걸 별도 카드가 아니라 면책 문구 바로 위에 1~2줄로 축약:

```html
<!-- 기존 면책/구독해지 영역에 통합 -->
<td style="padding:6px 8px;color:#94a3b8;font-size:11px;line-height:1.6;text-align:center;">
  데이터: FRED · Stooq · CoinGecko · Perplexity · Grok X Search<br>
  본 메일은 공개 시장 데이터 기반 정보성 브리핑이며 투자 권유가 아닙니다.<br>
  <a href="..." style="color:#94a3b8;">구독 해지</a> · <a href="..." style="color:#94a3b8;">GitHub</a>
</td>
```

### 뉴스 출처 처리

뉴스 헤드라인별 출처 나열은 제거. 대신:
- LAYER 2 뉴스 카드의 각 헤드라인에 출처명을 인라인으로 표시 (현재 프롬프트에서 `[출처: ...]` 형식으로 이미 생성)
- 별도 "뉴스 출처" 섹션 불필요

### 변경 요약

| 현재 | 제안 |
|---|---|
| ⑧ 데이터 출처 카드 (뉴스 + 시장 데이터) | **카드 제거** |
| 뉴스 출처 헤드라인별 나열 | 각 뉴스 bullet에 인라인 출처 (이미 있음) |
| 시장 데이터 4줄 | footer에 1줄 하드코딩 |
| 면책 문구 별도 영역 | 데이터 출처 + 면책 + 구독해지를 3줄로 통합 |

---

## 12. 최적화 후 이메일 구조 (Before → After)

### Before (현재 9개 섹션)
```
① 헤더
② 데이터 품질 알림 (조건부)
③ 핵심 요약 히어로 (LAYER 1)
④ 주요 뉴스 (LAYER 2)
⑤ 시장 흐름 (LAYER 3)
⑥ 거시 지표
⑦ 체크포인트
⑧ 데이터 출처
⑨ 면책/구독해지
```

### After (6개 섹션)
```
① 헤더 (트렌디 미니멀 디자인, 시장 스냅샷 배지 포함)
② 데이터 품질 알림 (조건부)
③ 시장 판단 + 핵심 수치 + 체크포인트 (통합 히어로)
④ 주요 뉴스 (시각적 계층 분리, 인라인 출처)
⑤ 종목 + 거시 지표 (통합, 컬러 배지 통일)
⑥ footer (데이터 출처 1줄 + 면책 + 구독해지)
```

제거된 것:
- ⑦ 체크포인트 카드 → ③에 통합
- ⑧ 데이터 출처 카드 → ⑥ footer 1줄로
- 거시 지표 별도 카드 → ⑤에 통합

Content was rephrased for compliance with licensing restrictions.

References:
- [1] Mailtrap Email Design Trends - https://mailtrap.io/blog/email-design-trends/
- [2] Brevo Email Design Best Practices - https://www.brevo.com/blog/email-design-best-practices/
- [3] HTML Arrow Entities - https://www.toptal.com/designers/htmlarrows/arrows/
- [4] codegenes.net Triangle Characters - https://www.codegenes.net/blog/what-characters-can-be-used-for-up-down-triangle-arrow-without-stem-for-display-in-html/
