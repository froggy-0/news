# 설계 문서: 이메일 브리핑 리디자인

## 개요

아침 시황 브리핑 이메일의 프레젠테이션 레이어를 전면 리디자인한다. 기존 3-LAYER 텍스트 중심 구조를 mail.md 기획안 기반의 모던 섹션 구조(Section 0~7)로 전환하고, Jinja2 프롬프트 템플릿과 HTML 이메일 템플릿을 동시에 재설계한다. 데이터 수집 인프라(`pipeline.py`의 데이터 수집 단계)는 변경하지 않으며, LLM 출력 포맷(`prompting.py`, `brief_formatting.py`)과 이메일 렌더링(`emailer.py`, 템플릿 파셜)만 대상으로 한다.

### 변경 범위 요약

| 레이어 | 현재 | 변경 후 |
|--------|------|---------|
| LLM 프롬프트 | `brief_instructions.j2` (3-LAYER 구조) | Section 0~6 구조 + 친근한 한국어 어투 |
| LLM 입력 | `brief_input.j2` (3-LAYER 지시) | Section 기반 지시 + sonar/x 조건부 |
| 포맷터 | `brief_formatting.py` (LAYER 파싱) | Section 기반 파싱 + 새 데이터 모델 |
| 이메일 빌더 | `emailer.py` (단일 컨텍스트 빌드) | 새 섹션 컨텍스트 빌드 + BTC/이벤트 추가 |
| HTML 템플릿 | `email.html.j2` (단일 파일, 9개 카드) | 6개 파셜 + 3개 조건부 파셜 + 매크로 |
| 텍스트 템플릿 | `email.txt.j2` | 새 섹션 구조에 맞춰 업데이트 |

## 하이레벨 아키텍처

```
packet (JSON)
    │
    ▼
prompting.py ──► brief_instructions.j2 (시스템 프롬프트)
    │              brief_input.j2 (사용자 프롬프트)
    │
    ▼
LLM API ──► 새 섹션 구조 텍스트 출력
    │
    ▼
brief_formatting.py ──► extract_sections() → SectionMap
    │                    parse_news_items() → list[NewsItem]
    │                    parse_sector_mapping() → SectorMapping
    │                    parse_event_calendar() → list[EventItem]
    │
    ▼
emailer.py ──► _build_email_context_v2() → dict
    │
    ▼
email_base.html.j2 ──► {% include %} 파셜들
    │
    ▼
최종 HTML 이메일
```

## 1. 데이터 모델 설계

### 1.1 새 섹션 파싱 결과 타입 (요구사항 6)

```python
# brief_formatting.py 에 추가

class SectionMap(TypedDict, total=False):
    """LLM 출력을 섹션별로 파싱한 결과"""
    title: str                    # 브리핑 제목
    section_0: str                # 오늘의 핵심 (30초 요약)
    section_1: str                # 거시 지표 Dashboard
    section_2: str                # 미국 증시
    section_3: str                # BTC & 크립토
    section_4_1: str              # 이슈 브리핑
    section_4_2: str              # 핵심 뉴스 5선
    section_4_3: str              # 섹터/자산 영향 매핑
    section_5_1: str              # 주간 맥락 연결
    section_5_2: str              # Sonar 교차 분석
    section_5_3: str              # X 시장 반응
    section_6: str                # 이벤트 캘린더

class NewsItemV2(TypedDict):
    """Section 4-2 뉴스 아이템 파싱 결과"""
    number: str                   # ①~⑤
    headline: str                 # 한국어 헤드라인
    body: str                     # 5~8문장 서술 단락
    source_name: str | None       # 출처명 (Reuters, Bloomberg 등)
    source_url: str | None        # 원문 링크
    tldr: str                     # 핵심 한줄 요약
    source_tier: int | None       # 1=Tier1, 2+=기타

class SectorMappingItem(TypedDict):
    """Section 4-3 개별 매핑 항목"""
    ticker: str                   # 종목/자산 코드
    name: str                     # 표시명
    reason: str                   # 판단 근거 한 줄

class SectorMapping(TypedDict):
    """Section 4-3 전체 매핑"""
    positive: list[SectorMappingItem]   # 수혜 방향
    negative: list[SectorMappingItem]   # 압력 방향
    neutral: list[SectorMappingItem]    # 중립/관망
    commentary: str                      # 서술 보강 1~2문장

class EventItem(TypedDict):
    """Section 6 이벤트 캘린더 항목"""
    date: str                     # 날짜 (3/18 화)
    time: str                     # 시간 (21:30)
    name: str                     # 이벤트명
    expected: str                 # 예상치
    impact: int                   # 1~5 (■ 개수)
    is_today: bool                # 오늘 발표 여부

class MacroIndicator(TypedDict):
    """Section 1 거시 지표 항목"""
    label: str                    # 지표명 (10년물, DXY 등)
    value: str                    # 현재 값
    change: str                   # 변동 (+0.08%p 등)
    direction: str                # up / down / flat
    is_previous: bool             # 전일 값 여부
    is_anomaly: bool              # 이상값 여부

class StockItem(TypedDict):
    """Section 2 종목 항목"""
    ticker: str                   # NVDA, AAPL 등
    name: str                     # 표시명
    price: str                    # 현재가
    change_pct: str               # 등락률
    direction: str                # up / down / flat
    volume: str | None            # 거래량 (선택)

class BTCData(TypedDict, total=False):
    """Section 3 BTC 데이터"""
    spot_price: str               # BTC 현물가
    spot_change: str              # 등락률
    spot_direction: str           # up / down / flat
    fear_greed_value: int         # 공포탐욕지수 (0~100)
    fear_greed_label: str         # Extreme Fear / Fear / Greed / Extreme Greed
    fear_greed_warning: str       # 과열 경계 (75 이상 시)
    etf_items: list[dict]         # ETF 목록 (ticker, price, change, volume)
    etf_total_volume: str         # ETF 합산 거래량
    official_snapshots: list[dict]  # 기관 보유 현황
    daily_flow_btc: float         # 순유입/유출 BTC
    daily_flow_usd: str           # 순유입/유출 USD
    flow_label: str               # 기관 순매수 / 기관 순매도
```

### 1.2 이메일 컨텍스트 변수 (emailer.py → 템플릿)

`_build_email_context_v2()` 가 반환하는 딕셔너리 키:

| 변수명 | 타입 | 용도 | 요구사항 |
|--------|------|------|----------|
| `subject` | str | 메일 제목 | R12 |
| `preheader` | str | 받은편지함 미리보기 | R12 |
| `display_date` | str | 헤더 날짜 표시 | R2 |
| `read_time` | str | 읽기 시간 ("3분 읽기") | R2 |
| `snapshot_badges` | list[dict] | 스냅샷 대시보드 4개 배지 | R2, R3 |
| `hero_summary` | str | Section 0 핵심 요약 | R1, R5 |
| `hero_alerts` | list[str] | 이상 움직임 감지 항목 | R5 |
| `macro_indicators` | list[MacroIndicator] | Section 1 거시 지표 | R1 |
| `stock_indices` | list[StockItem] | Section 2 주요 지수 | R1 |
| `stock_tech` | list[StockItem] | Section 2 빅테크 10종 | R1 |
| `btc_data` | BTCData | Section 3 BTC 전체 | R7 |
| `issue_briefings` | list[dict] | Section 4-1 이슈 브리핑 | R5 |
| `news_items` | list[NewsItemV2] | Section 4-2 핵심 뉴스 | R4, R5 |
| `sector_mapping` | SectorMapping \| None | Section 4-3 섹터 매핑 | R13 |
| `weekly_context` | str | Section 5-1 주간 맥락 | R5 |
| `sonar_analyses` | list[dict] \| None | Section 5-2 Sonar 분석 | R5 |
| `x_reactions` | str \| None | Section 5-3 X 반응 | R5 |
| `event_calendar` | list[EventItem] \| None | Section 6 이벤트 | R10 |
| `data_quality_status` | str | ok / degraded / critical | R9 |
| `footer_notes` | list[str] | 데이터 품질 각주 | R9, R11 |
| `unsubscribe_url` | str | 구독 해지 링크 | R11 |
| `github_url` | str | GitHub 링크 | R11 |

## 2. 프롬프트 템플릿 재설계 (요구사항 5, 10, 12, 13)

### 2.1 brief_instructions.j2 변경

기존 3-LAYER `<output_contract>` 를 Section 0~6 구조로 전면 교체한다.

#### 새 출력 계약 구조

```
<output_contract>
제목: "Morning Market Brief (YYYY-MM-DD)"

본문 섹션 (번호 순서 필수):
  0. 오늘의 핵심 (30초 요약)
     - 핵심 내러티브 1~3문장
     - 이상 움직임 감지 시 추가 bullet

  1. 거시 지표 Dashboard
     - 미국 국채 (10년물, 2년물, 3개월물, 스프레드)
     - 달러 & 변동성 (DXY, VIX, 원/달러)
     - 선물 (나스닥 선물)

  2. 미국 증시
     - 주요 지수 (SPY, QQQ, SOXX)
     - 빅테크 10종 (변동 폭 큰 순)

  3. BTC & 크립토
     - BTC 현물 + 공포탐욕지수
     - BTC 현물 ETF 5종 (IBIT, FBTC, ARKB, BITB, GBTC)
     - 기관 보유 현황 (official_etf_snapshots 존재 시)

  4-1. 이슈 브리핑 (토픽별 서술)
     - Bloomberg 스타일 서술 단락, 토픽당 3~5문장

  4-2. 핵심 뉴스 5선
     - ①~⑤ 번호 + 헤드라인 + 서술 5~8문장 + 원문 링크
     - 핵심 한줄 (TL;DR) 포함

  4-3. 섹터/자산 영향 매핑
     - 수혜(+) / 압력(-) / 중립 3분류
     - 각 항목에 판단 근거 한 줄 필수
     - 서술 보강 1~2문장

  5-1. 주간 맥락 연결
     - 요일별 고정 틀 (월/화~목/금)

  5-2. Sonar 교차 분석 (sonar_context 존재 시)
     - 최대 3건, 4~6문장 서술

  5-3. X 시장 반응 (x_market_signals 1건+ 시)
     - 2~3단락 압축 서술, 계정 핸들 인라인

  6. 이벤트 캘린더
     - 오늘 발표 예정 상단 분리
     - 이번 주 나머지 날짜순
     - 5단계 영향도 (■□ 기반)
</output_contract>
```

#### 새 문체 규칙 (`<style_rules>`)

```
<style_rules>
- 문체: 시장을 잘 아는 친구가 카톡으로 설명해주는 느낌의 따뜻한 존댓말
- 허용 어미: "~이에요", "~네요", "~거든요", "~해요", "~볼 만해요"
- 금지 어미: "~입니다", "~하였습니다", "~됩니다" (딱딱한 격식체)
- 금융 전문 용어: 반드시 일반인 수준 부연 설명 포함
  예: "VIX(시장의 불안감을 숫자로 나타낸 지표예요)"
- 숫자 설명: 단순 나열 금지, 의미를 풀어서 설명
  예: "미국 대표 기업 500개의 평균 주가가 0.8% 떨어졌어요"
- 분량: 깊이 우선, 뉴스당 5~8문장까지 확장 허용
- 줄띄기: 핵심 포인트는 별도 줄, 문장 사이 충분한 줄바꿈
- 단정적 표현 금지: "급등", "급락", "폭등", "폭락"
- 인과관계 서술: 상관관계 중심 ("함께 움직였어요", "영향을 받은 것으로 보여요")
</style_rules>
```

### 2.2 brief_input.j2 변경

기존 LAYER 기반 작성 지침을 Section 기반으로 교체한다.

주요 변경:
- `1. LAYER 1 | ...` → `0. 오늘의 핵심` ~ `6. 이벤트 캘린더` 순서 지시
- 조건부 섹션 지시 추가: `{% if sonar_context %}` → Section 5-2 생성 지시
- 조건부 섹션 지시 추가: `{% if x_market_signals %}` → Section 5-3 생성 지시
- 문체 지시: 격식체 → 친근한 존댓말로 전환
- 분량 지시: "3~5분 읽기" 제한 제거, 깊이 우선

### 2.3 메일 제목 생성 (요구사항 12)

`emailer.py`의 `_build_email_context_v2()` 에서 제목 생성 로직 추가:

```python
def _build_subject_line(section_map: SectionMap, packet: dict) -> str:
    """[날짜 요일] 브리핑 — [지수 등락] · [BTC 가격] · [핵심 변수]"""
    date_str = _format_subject_date(packet)  # "3/18 화"
    sp500_change = _extract_index_change(packet, "SPY")  # "S&P -0.8%"
    btc_price = _extract_btc_price(packet)  # "BTC $87,200"
    key_event = _extract_key_event(section_map)  # "소매판매 21:30"
    
    subject = f"{date_str} 브리핑 — {sp500_change} · {btc_price} · {key_event}"
    
    # data_quality.status == critical 시 프리픽스
    if packet.get("data_quality", {}).get("status") == "critical":
        subject = f"[데이터 참고] {subject}"
    
    return subject
```

## 3. 포맷터 재설계 (요구사항 6)

### 3.1 새 섹션 파싱 함수

`brief_formatting.py`에 기존 `extract_brief_structure()` 를 대체하는 새 함수:

```python
# 섹션 헤딩 패턴
SECTION_HEADING_V2_RE = re.compile(
    r"^(\d+(?:-\d+)?)\.\s+(.+)$"
)

def extract_sections(body: str) -> SectionMap:
    """새 섹션 구조(0~6)의 LLM 출력을 파싱하여 SectionMap 반환.
    
    누락된 섹션은 빈 문자열로 처리.
    기존 LAYER 구조 감지 시 레거시 파싱으로 폴백.
    """
    lines = body.replace("\r\n", "\n").split("\n")
    title = lines[0].strip() if lines else "Morning Market Brief"
    
    section_map: SectionMap = {"title": title}
    current_key: str | None = None
    current_lines: list[str] = []
    
    SECTION_KEY_MAP = {
        "0": "section_0",
        "1": "section_1",
        "2": "section_2",
        "3": "section_3",
        "4-1": "section_4_1",
        "4-2": "section_4_2",
        "4-3": "section_4_3",
        "5-1": "section_5_1",
        "5-2": "section_5_2",
        "5-3": "section_5_3",
        "6": "section_6",
    }
    
    for line in lines[1:]:
        match = SECTION_HEADING_V2_RE.match(line.strip())
        if match:
            if current_key:
                section_map[current_key] = "\n".join(current_lines).strip()
            num = match.group(1)
            current_key = SECTION_KEY_MAP.get(num)
            current_lines = []
        elif current_key:
            current_lines.append(line)
    
    if current_key:
        section_map[current_key] = "\n".join(current_lines).strip()
    
    return section_map
```

### 3.2 뉴스 아이템 파싱 (Section 4-2)

```python
NEWS_ITEM_RE = re.compile(r"^[①②③④⑤]\s+(.+?)(?:\s*[—–]\s*(.+))?$")
LINK_RE = re.compile(r"→\s*원문\s*(?:링크)?\s*(https?://\S+)")
TLDR_RE = re.compile(r"핵심\s*한줄[:\s]*(.+)")

def parse_news_items(section_4_2: str) -> list[NewsItemV2]:
    """Section 4-2 텍스트를 NewsItemV2 리스트로 파싱."""
    items: list[NewsItemV2] = []
    # ①~⑤ 기준으로 분할 후 각 블록 파싱
    blocks = re.split(r"(?=^[①②③④⑤])", section_4_2, flags=re.MULTILINE)
    
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.splitlines()
        # 첫 줄에서 번호 + 헤드라인 + 출처 추출
        first_match = NEWS_ITEM_RE.match(lines[0].strip())
        if not first_match:
            continue
        headline = first_match.group(1).strip()
        source_name = first_match.group(2).strip() if first_match.group(2) else None
        
        # 나머지 줄에서 본문, 링크, TL;DR 추출
        body_lines, url, tldr = [], None, ""
        for line in lines[1:]:
            link_match = LINK_RE.search(line)
            if link_match:
                url = link_match.group(1)
                continue
            tldr_match = TLDR_RE.match(line.strip())
            if tldr_match:
                tldr = tldr_match.group(1).strip()
                continue
            body_lines.append(line)
        
        items.append(NewsItemV2(
            number=block[0],
            headline=headline,
            body="\n".join(body_lines).strip(),
            source_name=source_name,
            source_url=url,
            tldr=tldr,
            source_tier=1 if source_name and source_name in _TIER1_SOURCES else None,
        ))
    
    return items[:5]

_TIER1_SOURCES = {"Reuters", "Bloomberg", "WSJ", "FT", "CNBC", "CoinDesk",
                  "The Wall Street Journal", "Financial Times"}
```

### 3.3 섹터 매핑 파싱 (Section 4-3)

```python
SECTOR_DIRECTION_RE = re.compile(r"^(수혜|압력|중립)\s*(?:방향)?\s*\(([+\-]?)\)")

def parse_sector_mapping(section_4_3: str) -> SectorMapping | None:
    """Section 4-3 텍스트를 SectorMapping으로 파싱.
    3분류 중 하나라도 비어있으면 None 반환 (요구사항 13-4).
    """
    mapping: SectorMapping = {
        "positive": [], "negative": [], "neutral": [], "commentary": ""
    }
    current_direction: str | None = None
    commentary_lines: list[str] = []
    in_commentary = False
    
    for line in section_4_3.splitlines():
        stripped = line.strip()
        if not stripped:
            if current_direction and mapping[current_direction]:
                in_commentary = True
            continue
        
        dir_match = SECTOR_DIRECTION_RE.match(stripped)
        if dir_match:
            label = dir_match.group(1)
            current_direction = {"수혜": "positive", "압력": "negative", "중립": "neutral"}[label]
            in_commentary = False
            continue
        
        if in_commentary:
            commentary_lines.append(stripped)
            continue
        
        if current_direction and stripped.startswith(("  ", "\t")):
            parts = stripped.strip().split(None, 1)
            if len(parts) >= 2:
                mapping[current_direction].append(SectorMappingItem(
                    ticker=parts[0], name=parts[0], reason=parts[1]
                ))
    
    mapping["commentary"] = "\n".join(commentary_lines).strip()
    
    # 3분류 모두 1개 이상 있어야 유효
    if not mapping["positive"] or not mapping["negative"] or not mapping["neutral"]:
        return None
    
    return mapping
```

### 3.4 이벤트 캘린더 파싱 (Section 6)

```python
EVENT_LINE_RE = re.compile(
    r"(\d{1,2}:\d{2})?\s*(.+?)\s+(?:예상\s+)?([^\s■□]+)?\s*((?:[■□]){1,5})"
)

def parse_event_calendar(section_6: str) -> list[EventItem]:
    """Section 6 텍스트를 EventItem 리스트로 파싱."""
    items: list[EventItem] = []
    current_date = ""
    is_today_block = False
    
    for line in section_6.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if "오늘" in stripped:
            is_today_block = True
            # 날짜 추출
            date_match = re.search(r"\d{1,2}/\d{1,2}", stripped)
            current_date = date_match.group(0) if date_match else ""
            continue
        if "이번 주" in stripped:
            is_today_block = False
            continue
        if re.match(r"\d{1,2}/\d{1,2}", stripped):
            current_date = re.match(r"\d{1,2}/\d{1,2}", stripped).group(0)
            is_today_block = False
            continue
        
        match = EVENT_LINE_RE.match(stripped)
        if match:
            impact_str = match.group(4)
            items.append(EventItem(
                date=current_date,
                time=match.group(1) or "",
                name=match.group(2).strip(),
                expected=match.group(3) or "",
                impact=impact_str.count("■"),
                is_today=is_today_block,
            ))
    
    return items
```

### 3.5 라운드트립 속성 (요구사항 6-6)

포맷터의 정확성을 보장하기 위해, 파싱 → 직렬화 → 재파싱 라운드트립 속성을 검증한다:

```python
def serialize_sections(section_map: SectionMap) -> str:
    """SectionMap을 LLM 출력 형식 텍스트로 직렬화."""
    SECTION_TITLES = {
        "section_0": "0. 오늘의 핵심",
        "section_1": "1. 거시 지표 Dashboard",
        "section_2": "2. 미국 증시",
        "section_3": "3. BTC & 크립토",
        "section_4_1": "4-1. 이슈 브리핑",
        "section_4_2": "4-2. 핵심 뉴스 5선",
        "section_4_3": "4-3. 섹터/자산 영향 매핑",
        "section_5_1": "5-1. 주간 맥락 연결",
        "section_5_2": "5-2. Sonar 교차 분석",
        "section_5_3": "5-3. X 시장 반응",
        "section_6": "6. 이벤트 캘린더",
    }
    parts = [section_map.get("title", "Morning Market Brief")]
    for key, title in SECTION_TITLES.items():
        content = section_map.get(key, "")
        if content:
            parts.append(f"\n{title}\n{content}")
    return "\n".join(parts)

# 라운드트립 속성: extract_sections(serialize_sections(m)) == m
```

## 4. 이메일 빌더 재설계 (emailer.py)

### 4.1 _build_email_context_v2()

기존 `_build_email_context()` 를 대체하는 새 컨텍스트 빌드 함수:

```python
def _build_email_context_v2(
    subject: str, body: str, packet: dict, *, sender: str = ""
) -> dict[str, object]:
    """새 섹션 구조 기반 이메일 컨텍스트 빌드."""
    section_map = extract_sections(body)
    
    # 스냅샷 대시보드 (요구사항 2)
    snapshot_badges = _build_snapshot_badges(packet)
    
    # 뉴스 아이템 (요구사항 4)
    news_items = parse_news_items(section_map.get("section_4_2", ""))
    
    # 섹터 매핑 (요구사항 13)
    sector_mapping = parse_sector_mapping(section_map.get("section_4_3", ""))
    
    # BTC 데이터 (요구사항 7)
    btc_data = _build_btc_data(packet, section_map.get("section_3", ""))
    
    # 이벤트 캘린더 (요구사항 10)
    events = parse_event_calendar(section_map.get("section_6", ""))
    event_calendar = events if events else None
    
    # 거시 지표 (요구사항 1)
    macro_indicators = _parse_macro_indicators(section_map.get("section_1", ""))
    
    # 종목 (요구사항 1)
    stock_indices, stock_tech = _parse_stocks(section_map.get("section_2", ""))
    
    # 데이터 품질 (요구사항 9)
    dq = packet.get("data_quality", {})
    data_quality_status = dq.get("status", "ok")
    footer_notes = packet.get("data_footer_notes", [])
    
    # 제목 생성 (요구사항 12)
    final_subject = _build_subject_line(section_map, packet) if not subject else subject
    
    return {
        "subject": final_subject,
        "preheader": _build_preheader(snapshot_badges, section_map),
        "display_date": _format_display_date_v2(packet),
        "read_time": "3분 읽기",
        "snapshot_badges": snapshot_badges,
        "hero_summary": section_map.get("section_0", ""),
        "macro_indicators": macro_indicators,
        "stock_indices": stock_indices,
        "stock_tech": stock_tech,
        "btc_data": btc_data,
        "issue_briefings": _parse_issue_briefings(section_map.get("section_4_1", "")),
        "news_items": news_items,
        "sector_mapping": sector_mapping,
        "weekly_context": section_map.get("section_5_1", ""),
        "sonar_analyses": _parse_sonar(section_map.get("section_5_2", "")),
        "x_reactions": section_map.get("section_5_3", "") or None,
        "event_calendar": event_calendar,
        "data_quality_status": data_quality_status,
        "footer_notes": footer_notes if data_quality_status != "ok" else [],
        "unsubscribe_url": _unsubscribe_url(sender),
        "github_url": PROJECT_GITHUB_URL,
    }
```

### 4.2 스냅샷 대시보드 빌더 (요구사항 2, 3)

```python
def _build_snapshot_badges(packet: dict) -> list[dict]:
    """S&P 500, 나스닥, BTC, VIX 4개 배지 생성."""
    badges = []
    
    # US indices
    for idx in packet.get("us_indices", []):
        ticker = idx.get("ticker", "")
        if ticker in ("SPY", "QQQ"):
            label = "S&P 500" if ticker == "SPY" else "나스닥"
            change = idx.get("change_pct", 0)
            badges.append({
                "label": label,
                "value": f"{change:+.1f}%",
                "direction": "up" if change > 0 else "down" if change < 0 else "flat",
            })
    
    # BTC
    btc = packet.get("bitcoin", {})
    btc_change = btc.get("spot", {}).get("change_pct", 0)
    badges.append({
        "label": "BTC",
        "value": f"{btc_change:+.1f}%",
        "direction": "up" if btc_change > 0 else "down" if btc_change < 0 else "flat",
    })
    
    # VIX
    macro = packet.get("macro", {})
    vix = macro.get("VIX", {})
    vix_val = vix.get("value", 0)
    badges.append({
        "label": "VIX",
        "value": f"{vix_val:.1f}",
        "direction": "up" if vix_val >= 25 else "flat",
    })
    
    return badges[:4]
```

### 4.3 BTC 데이터 빌더 (요구사항 7)

```python
FEAR_GREED_LABELS = {
    (0, 24): "Extreme Fear",
    (25, 49): "Fear",
    (50, 74): "Greed",
    (75, 100): "Extreme Greed",
}

def _build_btc_data(packet: dict, section_3: str) -> BTCData:
    """packet의 bitcoin 데이터로 BTCData 구성."""
    btc = packet.get("bitcoin", {})
    spot = btc.get("spot", {})
    fg_value = btc.get("fear_greed_value", 50)
    
    # 공포탐욕 레이블
    fg_label = "Greed"
    for (lo, hi), label in FEAR_GREED_LABELS.items():
        if lo <= fg_value <= hi:
            fg_label = label
            break
    
    # ETF 유입/유출
    flow_btc = btc.get("official_etf_daily_flow_btc", 0)
    flow_label = "기관 순매수" if flow_btc > 0 else "기관 순매도" if flow_btc < 0 else ""
    
    return BTCData(
        spot_price=f"${spot.get('price', 0):,.0f}",
        spot_change=f"{spot.get('change_pct', 0):+.1f}%",
        spot_direction="up" if spot.get("change_pct", 0) > 0 else "down" if spot.get("change_pct", 0) < 0 else "flat",
        fear_greed_value=fg_value,
        fear_greed_label=fg_label,
        fear_greed_warning="과열 경계" if fg_value >= 75 else "",
        etf_items=btc.get("etf_points", []),
        etf_total_volume=_format_volume(sum(e.get("volume", 0) for e in btc.get("etf_points", []))),
        official_snapshots=btc.get("official_etf_snapshots", []),
        daily_flow_btc=flow_btc,
        daily_flow_usd=f"${abs(flow_btc) * spot.get('price', 0):,.0f}",
        flow_label=flow_label,
    )
```

## 5. 이메일 템플릿 파셜 구조 (요구사항 16)

### 5.1 파일 구조

```
src/morning_brief/templates/
├── email_base.html.j2          # 마스터 레이아웃 (head + style + include)
├── email_header.html.j2        # 헤더 + 스냅샷 대시보드
├── email_hero.html.j2          # Section 0 핵심 요약 히어로
├── email_news.html.j2          # Section 4-2 뉴스 카드 반복
├── email_market.html.j2        # Section 1+2 종목 + 거시 콤팩트
├── email_btc.html.j2           # Section 3 BTC 전용 (조건부)
├── email_sector.html.j2        # Section 4-3 섹터 매핑 (조건부)
├── email_calendar.html.j2      # Section 6 이벤트 캘린더 (조건부)
├── email_footer.html.j2        # 출처 + 면책 + 품질 각주
├── email_macros.html.j2        # 공통 매크로 (badge, kr_label 등)
├── email.html.j2               # 레거시 호환 (email_base로 리다이렉트)
└── email.txt.j2                # 텍스트 버전 (업데이트)
```

### 5.2 email_macros.html.j2 — 공통 매크로 (요구사항 3, 14)

```jinja2
{# 컬러 배지 매크로 — 모든 파셜에서 import하여 사용 #}
{% macro badge(value, direction) %}
<span style="display:inline-block;
  background:{% if direction == 'up' %}#dcfce7{% elif direction == 'down' %}#fef2f2{% else %}#f3f4f6{% endif %};
  color:{% if direction == 'up' %}#166534{% elif direction == 'down' %}#991b1b{% else %}#4b5563{% endif %};
  padding:2px 8px;border-radius:4px;font-size:13px;
  font-weight:{% if value|replace('%','')|replace('+','')|replace('-','')|float > 3 %}800{% else %}700{% endif %};
  font-variant-numeric:tabular-nums;">
  {% if direction == 'up' %}&#9650;{% elif direction == 'down' %}&#9660;{% else %}&#8212;{% endif %} {{ value }}
</span>
{% endmacro %}

{# KR 라벨 매크로 #}
{% macro kr_label() %}
<span style="display:inline-block;border:1px solid #166534;border-radius:3px;
  padding:1px 5px;color:#166534;font-size:11px;font-weight:700;">KR</span>
{% endmacro %}

{# 섹션 라벨 매크로 (이모지 대체) #}
{% macro section_label(text, color) %}
<td style="border-left:3px solid {{ color }};padding-left:12px;
  font-family:'Apple SD Gothic Neo','Noto Sans KR',sans-serif;
  color:{{ color }};font-size:13px;font-weight:600;">{{ text }}</td>
{% endmacro %}

{# 데이터 품질 인라인 마크 #}
{% macro quality_mark(text) %}
<span style="font-size:11px;color:#94a3b8;">({{ text }})</span>
{% endmacro %}
```

### 5.3 email_base.html.j2 — 마스터 레이아웃

```jinja2
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <meta name="color-scheme" content="light dark">
  <title>{{ subject }}</title>
  <!--[if mso]><style>
    .card{border-radius:0!important}
    .gradient-line{background:#3b82f6!important}
  </style><![endif]-->
  <style>
    :root{color-scheme:light dark}
    @media(prefers-color-scheme:dark){
      body,.shell{background:#111!important}
      .card{background:#1a1a1a!important;border-color:#2a2a2a!important}
      .text-strong{color:#e8e8e3!important}
      .text-body{color:#d1d5db!important}
      .text-muted{color:#9ca3af!important}
      .badge-up{background:#14532d!important;color:#4ade80!important}
      .badge-down{background:#450a0a!important;color:#fca5a5!important}
      .badge-flat{background:#1f2937!important;color:#9ca3af!important}
      .hero-box{background:#1a2332!important}
      .kr-label{border-color:#4ade80!important;color:#4ade80!important}
      a{color:#93c5fd!important}
    }
    @media screen and (max-width:600px){
      .shell-pad{padding:12px 8px!important}
      .card-pad{padding:16px!important}
      .hero-title{font-size:28px!important}
      .text-body{font-size:15px!important}
      .snapshot-badge{display:block!important;margin-bottom:8px!important}
      a{min-height:44px;display:inline-block;line-height:44px}
    }
  </style>
</head>
<body style="margin:0;padding:0;background:#f5f5f0;">
  <div style="display:none;max-height:0;overflow:hidden;">{{ preheader }}</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
    class="shell" style="width:100%;background:#f5f5f0;">
    <tr><td align="center" class="shell-pad" style="padding:24px 14px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
        style="max-width:640px;">
        {% include "email_header.html.j2" %}
        {% include "email_hero.html.j2" %}
        {% if news_items %}{% include "email_news.html.j2" %}{% endif %}
        {% if btc_data %}{% include "email_btc.html.j2" %}{% endif %}
        {% include "email_market.html.j2" %}
        {% if sector_mapping %}{% include "email_sector.html.j2" %}{% endif %}
        {% if event_calendar %}{% include "email_calendar.html.j2" %}{% endif %}
        {% include "email_footer.html.j2" %}
      </table>
    </td></tr>
  </table>
</body>
</html>
```

### 5.4 email_header.html.j2 — 헤더 + 스냅샷 (요구사항 2, 3, 15)

```jinja2
{# 변수: display_date, read_time, snapshot_badges #}
{% from "email_macros.html.j2" import badge %}
<tr><td style="padding:0 0 24px 0;">
  <table role="presentation" width="100%" class="card" style="width:100%;background:#fff;
    border:1px solid #e2e8f0;border-radius:16px;">
    <tr><td class="card-pad" style="padding:32px 24px 20px 24px;">
      <div style="font-family:'Apple SD Gothic Neo','Noto Sans KR',sans-serif;
        color:#0f172a;font-size:15px;font-weight:600;letter-spacing:0.08em;
        text-transform:uppercase;">MORNING MARKET BRIEF</div>
      <div style="padding-top:6px;font-family:'Apple SD Gothic Neo','Noto Sans KR',sans-serif;
        color:#94a3b8;font-size:13px;">{{ display_date }} · {{ read_time }}</div>
      <div class="gradient-line" style="margin-top:20px;height:2px;
        background:linear-gradient(90deg,#cbd5e1,#3b82f6,#cbd5e1);"></div>
      {% if snapshot_badges %}
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
        style="padding-top:16px;">
        <tr>
          {% for b in snapshot_badges %}
          <td class="snapshot-badge" style="text-align:center;padding:4px;">
            <div style="font-size:11px;color:#94a3b8;font-weight:600;">{{ b.label }}</div>
            <div style="padding-top:2px;">{{ badge(b.value, b.direction) }}</div>
          </td>
          {% endfor %}
        </tr>
      </table>
      {% endif %}
    </td></tr>
  </table>
</td></tr>
```

### 5.5 email_hero.html.j2 — 핵심 요약 (요구사항 1, 5, 15)

```jinja2
{# 변수: hero_summary, hero_alerts #}
<tr><td style="padding:0 0 24px 0;">
  <table role="presentation" width="100%" class="card" style="width:100%;background:#fff;
    border:1px solid #e2e8f0;border-top:4px solid #1e40af;border-radius:0 0 16px 16px;">
    <tr><td class="card-pad" style="padding:28px 24px;">
      <div style="border-left:3px solid #1e40af;padding-left:12px;
        font-family:'Apple SD Gothic Neo','Noto Sans KR',sans-serif;
        color:#1e40af;font-size:13px;font-weight:600;">오늘의 핵심</div>
      <div class="hero-box" style="margin-top:16px;background:#f0f4ff;padding:20px;
        border-radius:8px;">
        <div class="hero-title text-strong" style="font-family:'Apple SD Gothic Neo','Noto Sans KR',sans-serif;
          color:#0f172a;font-size:32px;line-height:1.5;font-weight:800;
          letter-spacing:-0.03em;white-space:pre-line;">{{ hero_summary }}</div>
      </div>
      {% if hero_alerts %}
      <div style="padding-top:16px;">
        {% for alert in hero_alerts %}
        <div style="padding-top:8px;font-family:'Apple SD Gothic Neo','Noto Sans KR',sans-serif;
          color:#475569;font-size:14px;line-height:1.8;">&#9679; {{ alert }}</div>
        {% endfor %}
      </div>
      {% endif %}
    </td></tr>
  </table>
</td></tr>
```

### 5.6 email_news.html.j2 — 뉴스 카드 (요구사항 4, 15)

```jinja2
{# 변수: news_items (list[NewsItemV2]) #}
{% from "email_macros.html.j2" import kr_label %}
<tr><td style="padding:0 0 24px 0;">
  <table role="presentation" width="100%" class="card" style="width:100%;background:#fff;
    border:1px solid #e2e8f0;border-radius:16px;">
    <tr><td class="card-pad" style="padding:28px 24px;">
      <div style="border-left:3px solid #1e40af;padding-left:12px;
        font-family:'Apple SD Gothic Neo','Noto Sans KR',sans-serif;
        color:#1e40af;font-size:13px;font-weight:600;">&#9632; 핵심 뉴스</div>
      {% for item in news_items %}
      <div style="padding:20px 0 0 0;{% if not loop.first %}border-top:1px solid #e2e8f0;
        margin-top:16px;{% endif %}">
        {# 헤드라인 #}
        <div style="font-family:'Apple SD Gothic Neo','Noto Sans KR',sans-serif;
          color:#0f172a;font-size:20px;line-height:1.6;font-weight:800;">
          {{ item.number }} {{ item.headline }}
          {% if item.source_name %}
          <span style="font-size:13px;font-weight:{% if item.source_tier == 1 %}700{% else %}400{% endif %};
            color:#64748b;"> — {{ item.source_name }}</span>
          {% endif %}
        </div>
        {# 시장 의미 (왼쪽 border 강조) #}
        {% if item.body %}
        <div style="margin-top:12px;border-left:3px solid #3b82f6;padding:12px 16px;
          background:#f8fafc;font-family:'Apple SD Gothic Neo','Noto Sans KR',sans-serif;
          color:#334155;font-size:15px;line-height:1.9;white-space:pre-line;">{{ item.body }}</div>
        {% endif %}
        {# 원문 링크 #}
        {% if item.source_url %}
        <div style="padding-top:8px;">
          <a href="{{ item.source_url }}" style="color:#3b82f6;font-size:13px;
            text-decoration:none;">원문 보기 &#8594;</a>
        </div>
        {% endif %}
        {# 핵심 한줄 TL;DR #}
        {% if item.tldr %}
        <div style="margin-top:12px;padding:10px 14px;background:#f0fdf4;border-radius:6px;
          font-family:'Apple SD Gothic Neo','Noto Sans KR',sans-serif;
          color:#166534;font-size:14px;line-height:1.6;font-weight:600;">
          &#9679; 핵심 한줄: {{ item.tldr }}
        </div>
        {% endif %}
      </div>
      {% endfor %}
    </td></tr>
  </table>
</td></tr>
```

### 5.7 email_btc.html.j2 — BTC 전용 섹션 (요구사항 7)

```jinja2
{# 변수: btc_data (BTCData) #}
{% from "email_macros.html.j2" import badge %}
<tr><td style="padding:0 0 24px 0;">
  <table role="presentation" width="100%" class="card" style="width:100%;background:#fff;
    border:1px solid #e2e8f0;border-radius:16px;">
    <tr><td class="card-pad" style="padding:24px;">
      <div style="border-left:3px solid #f59e0b;padding-left:12px;
        font-family:'Apple SD Gothic Neo','Noto Sans KR',sans-serif;
        color:#92400e;font-size:13px;font-weight:600;">&#9632; BTC &amp; 크립토</div>
      {# BTC 현물 + 공포탐욕 #}
      <table role="presentation" width="100%" style="padding-top:16px;">
        <tr>
          <td style="font-family:'Apple SD Gothic Neo','Noto Sans KR',sans-serif;
            color:#0f172a;font-size:18px;font-weight:800;">
            BTC {{ btc_data.spot_price }}
            {{ badge(btc_data.spot_change, btc_data.spot_direction) }}
          </td>
          <td align="right" style="font-family:'Apple SD Gothic Neo','Noto Sans KR',sans-serif;
            color:#475569;font-size:14px;">
            공포탐욕 {{ btc_data.fear_greed_value }} / 100
            <span style="font-weight:600;">{{ btc_data.fear_greed_label }}</span>
            {% if btc_data.fear_greed_warning %}
            <span style="color:#991b1b;font-size:12px;font-weight:700;">
              &#9888; {{ btc_data.fear_greed_warning }}</span>
            {% endif %}
          </td>
        </tr>
      </table>
      {# ETF 목록 #}
      {% if btc_data.etf_items %}
      <table role="presentation" width="100%" style="padding-top:12px;font-size:13px;">
        <tr style="color:#94a3b8;font-weight:600;">
          <td>ETF</td><td align="right">가격</td>
          <td align="right">등락</td><td align="right">거래량</td>
        </tr>
        {% for etf in btc_data.etf_items %}
        <tr style="border-top:1px solid #e2e8f0;color:#334155;">
          <td style="padding:6px 0;font-weight:600;">{{ etf.ticker }}</td>
          <td align="right">${{ etf.price }}</td>
          <td align="right">{{ badge(etf.change_pct, etf.direction) }}</td>
          <td align="right" style="color:#94a3b8;">{{ etf.volume }}</td>
        </tr>
        {% endfor %}
        <tr style="border-top:1px solid #e2e8f0;color:#475569;font-weight:600;">
          <td style="padding:6px 0;">합산 거래량</td>
          <td colspan="3" align="right">{{ btc_data.etf_total_volume }}</td>
        </tr>
      </table>
      {% endif %}
      {# 기관 보유 현황 #}
      {% if btc_data.official_snapshots %}
      <div style="padding-top:12px;border-top:1px solid #e2e8f0;margin-top:12px;">
        <div style="font-size:12px;color:#94a3b8;font-weight:600;">기관 보유 현황</div>
        {% for snap in btc_data.official_snapshots %}
        <div style="padding-top:6px;font-size:13px;color:#334155;">
          {{ snap.issuer }} {{ snap.ticker }} — {{ snap.btc_held }} BTC · AUM {{ snap.aum }}
        </div>
        {% endfor %}
        {% if btc_data.flow_label %}
        <div style="padding-top:8px;font-size:14px;font-weight:700;
          color:{% if btc_data.daily_flow_btc > 0 %}#166534{% else %}#991b1b{% endif %};">
          전일 대비: {{ btc_data.flow_label }} {{ btc_data.daily_flow_usd }}
        </div>
        {% endif %}
      </div>
      {% endif %}
    </td></tr>
  </table>
</td></tr>
```

### 5.8 email_market.html.j2 — 종목 + 거시 콤팩트 (요구사항 1, 3)

```jinja2
{# 변수: stock_indices, stock_tech, macro_indicators #}
{% from "email_macros.html.j2" import badge, quality_mark %}
<tr><td style="padding:0 0 24px 0;">
  <table role="presentation" width="100%" class="card" style="width:100%;background:#f8fafc;
    border:1px solid #e2e8f0;border-radius:16px;">
    <tr><td class="card-pad" style="padding:20px 24px;">
      {# 주요 지수 #}
      <div style="border-left:3px solid #0f766e;padding-left:12px;
        font-family:'Apple SD Gothic Neo','Noto Sans KR',sans-serif;
        color:#0f766e;font-size:13px;font-weight:600;">&#9632; 시장 지표</div>
      {% if stock_indices %}
      <table role="presentation" width="100%" style="padding-top:10px;font-size:13px;">
        {% for s in stock_indices %}
        <tr style="border-top:1px solid #e2e8f0;">
          <td style="padding:6px 0;font-weight:600;color:#0f172a;">{{ s.ticker }}</td>
          <td style="color:#64748b;">{{ s.name }}</td>
          <td align="right">{{ s.price }}</td>
          <td align="right">{{ badge(s.change_pct, s.direction) }}</td>
        </tr>
        {% endfor %}
      </table>
      {% endif %}
      {# 빅테크 10종 #}
      {% if stock_tech %}
      <div style="padding-top:12px;font-size:12px;color:#94a3b8;font-weight:600;">빅테크 10종</div>
      <table role="presentation" width="100%" style="padding-top:6px;font-size:13px;">
        {% for s in stock_tech %}
        <tr>
          <td style="padding:4px 0;font-weight:600;color:#0f172a;">{{ s.ticker }}</td>
          <td align="right">{{ badge(s.change_pct, s.direction) }}</td>
        </tr>
        {% endfor %}
      </table>
      {% endif %}
      {# 거시 지표 #}
      {% if macro_indicators %}
      <div style="padding-top:12px;border-top:1px solid #e2e8f0;margin-top:8px;">
        <div style="font-size:12px;color:#94a3b8;font-weight:600;">거시 지표</div>
        <table role="presentation" width="100%" style="padding-top:6px;font-size:13px;">
          {% for m in macro_indicators %}
          <tr>
            <td style="padding:4px 0;color:#475569;font-weight:600;">{{ m.label }}</td>
            <td align="right" style="color:#0f172a;">
              {% if m.is_anomaly %}&#8212;{% else %}{{ m.value }}{% endif %}
              {% if m.is_previous %}{{ quality_mark("전일") }}{% endif %}
            </td>
            <td align="right">
              {% if not m.is_anomaly %}{{ badge(m.change, m.direction) }}{% endif %}
            </td>
          </tr>
          {% endfor %}
        </table>
      </div>
      {% endif %}
    </td></tr>
  </table>
</td></tr>
```

### 5.9 email_sector.html.j2 — 섹터 매핑 (요구사항 13)

```jinja2
{# 변수: sector_mapping (SectorMapping) #}
<tr><td style="padding:0 0 24px 0;">
  <table role="presentation" width="100%" class="card" style="width:100%;background:#fff;
    border:1px solid #e2e8f0;border-radius:16px;">
    <tr><td class="card-pad" style="padding:20px 24px;">
      <div style="border-left:3px solid #7c3aed;padding-left:12px;
        font-family:'Apple SD Gothic Neo','Noto Sans KR',sans-serif;
        color:#7c3aed;font-size:13px;font-weight:600;">&#9632; 오늘 주목 흐름</div>
      {# 수혜 #}
      <div style="padding-top:12px;">
        <div style="color:#166534;font-size:12px;font-weight:700;">&#9650; 수혜 방향</div>
        {% for item in sector_mapping.positive %}
        <div style="padding:4px 0 4px 16px;font-size:13px;color:#334155;">
          <span style="font-weight:600;">{{ item.ticker }}</span> {{ item.reason }}
        </div>
        {% endfor %}
      </div>
      {# 압력 #}
      <div style="padding-top:8px;">
        <div style="color:#991b1b;font-size:12px;font-weight:700;">&#9660; 압력 방향</div>
        {% for item in sector_mapping.negative %}
        <div style="padding:4px 0 4px 16px;font-size:13px;color:#334155;">
          <span style="font-weight:600;">{{ item.ticker }}</span> {{ item.reason }}
        </div>
        {% endfor %}
      </div>
      {# 중립 #}
      <div style="padding-top:8px;">
        <div style="color:#4b5563;font-size:12px;font-weight:700;">&#8212; 중립 / 관망</div>
        {% for item in sector_mapping.neutral %}
        <div style="padding:4px 0 4px 16px;font-size:13px;color:#334155;">
          <span style="font-weight:600;">{{ item.ticker }}</span> {{ item.reason }}
        </div>
        {% endfor %}
      </div>
      {# 서술 보강 #}
      {% if sector_mapping.commentary %}
      <div style="padding-top:12px;border-top:1px solid #e2e8f0;margin-top:8px;
        font-size:14px;color:#475569;line-height:1.8;">{{ sector_mapping.commentary }}</div>
      {% endif %}
    </td></tr>
  </table>
</td></tr>
```

### 5.10 email_calendar.html.j2 — 이벤트 캘린더 (요구사항 10)

```jinja2
{# 변수: event_calendar (list[EventItem]) #}
<tr><td style="padding:0 0 24px 0;">
  <table role="presentation" width="100%" class="card" style="width:100%;background:#fff;
    border:1px solid #e2e8f0;border-radius:16px;">
    <tr><td class="card-pad" style="padding:20px 24px;">
      <div style="border-left:3px solid #0369a1;padding-left:12px;
        font-family:'Apple SD Gothic Neo','Noto Sans KR',sans-serif;
        color:#0369a1;font-size:13px;font-weight:600;">&#9632; 이벤트 캘린더</div>
      <table role="presentation" width="100%" style="padding-top:10px;font-size:13px;">
        <tr style="color:#94a3b8;font-weight:600;">
          <td>시간</td><td>이벤트</td><td align="right">예상</td><td align="right">영향도</td>
        </tr>
        {% for evt in event_calendar %}
        {% if evt.is_today and loop.first %}
        <tr><td colspan="4" style="padding:8px 0 4px;color:#0369a1;font-weight:700;font-size:12px;">
          오늘 발표</td></tr>
        {% endif %}
        <tr style="border-top:1px solid #e2e8f0;
          {% if evt.is_today %}background:#f0f9ff;{% endif %}">
          <td style="padding:6px 0;color:#475569;">{{ evt.time or evt.date }}</td>
          <td style="color:#0f172a;font-weight:{% if evt.impact >= 4 %}700{% else %}400{% endif %};">
            {{ evt.name }}</td>
          <td align="right" style="color:#64748b;">{{ evt.expected }}</td>
          <td align="right" style="color:#0f172a;letter-spacing:1px;">
            {{ "&#9632;" * evt.impact }}{{ "&#9633;" * (5 - evt.impact) }}
          </td>
        </tr>
        {% endfor %}
      </table>
    </td></tr>
  </table>
</td></tr>
```

### 5.11 email_footer.html.j2 — Footer (요구사항 9, 11)

```jinja2
{# 변수: data_quality_status, footer_notes, unsubscribe_url, github_url #}
<tr><td style="padding:12px 8px 0 8px;text-align:center;
  font-family:'Apple SD Gothic Neo','Noto Sans KR',sans-serif;">
  <div class="text-muted" style="color:#94a3b8;font-size:11px;line-height:1.8;">
    데이터: FRED &#183; Stooq &#183; CoinGecko &#183; Perplexity &#183; Grok X Search
  </div>
  <div class="text-muted" style="color:#94a3b8;font-size:11px;line-height:1.8;padding-top:4px;">
    본 메일은 공개 시장 데이터 기반 정보성 브리핑이며 투자 권유가 아닙니다.
  </div>
  <div style="padding-top:4px;">
    <a href="{{ unsubscribe_url }}" style="color:#94a3b8;font-size:11px;
      text-decoration:underline;">구독 해지</a>
    <span style="color:#94a3b8;font-size:11px;"> &#183; </span>
    <a href="{{ github_url }}" style="color:#94a3b8;font-size:11px;
      text-decoration:underline;">GitHub</a>
  </div>
  {# 데이터 품질 각주 (degraded/critical 시에만) #}
  {% if data_quality_status != "ok" and footer_notes %}
  <div style="padding-top:8px;border-top:1px solid #e2e8f0;margin-top:8px;">
    {% for note in footer_notes %}
    <div style="color:#94a3b8;font-size:11px;line-height:1.6;">{{ note }}</div>
    {% endfor %}
  </div>
  {% endif %}
</td></tr>
```

## 6. 컬러 시스템 및 디자인 토큰 (요구사항 3, 8)

### 6.1 듀얼톤 컬러 팔레트

| 용도 | 라이트 모드 | 다크 모드 |
|------|------------|-----------|
| 배경 (body) | #f5f5f0 | #111111 |
| 카드 배경 | #ffffff | #1a1a1a |
| 카드 보더 | #e2e8f0 | #2a2a2a |
| 텍스트 (강조) | #0f172a | #e8e8e3 |
| 텍스트 (본문) | #334155 | #d1d5db |
| 텍스트 (뮤트) | #94a3b8 | #9ca3af |
| 브랜드 블루 | #1e40af | #3b82f6 |
| 상승 배경 | #dcfce7 | #14532d |
| 상승 텍스트 | #166534 | #4ade80 |
| 하락 배경 | #fef2f2 | #450a0a |
| 하락 텍스트 | #991b1b | #fca5a5 |
| 보합 배경 | #f3f4f6 | #1f2937 |
| 보합 텍스트 | #4b5563 | #9ca3af |

### 6.2 타이포그래피 스케일

| 요소 | 크기 | 굵기 | line-height |
|------|------|------|-------------|
| 히어로 제목 | 32~48px | 800 | 1.5 |
| 뉴스 헤드라인 | 20px | 800 | 1.6 |
| 본문 텍스트 | 15~16px | 400 | 1.8~2.0 |
| 섹션 라벨 | 13px | 600 | 1.4 |
| 배지 텍스트 | 13px | 700 | 1.0 |
| 콤팩트 데이터 | 13~14px | 400~600 | 1.6 |
| Footer | 11~12px | 400 | 1.8 |

### 6.3 간격 시스템

| 요소 | 데스크톱 | 모바일 |
|------|---------|--------|
| 카드 내부 패딩 | 24~28px | 16px |
| 카드 간 간격 | 24px | 16px |
| 섹션 간 간격 | 24px+ | 16px |
| 문단 간 간격 | 16px+ | 12px |
| 포인트 간 간격 | 12px+ | 8px |

## 7. 데이터 품질 처리 (요구사항 9)

### 7.1 상태별 동작 매트릭스

| 상태 | 메일 제목 | 본문 상단 | 수치 옆 | Footer |
|------|----------|----------|---------|--------|
| ok | 변경 없음 | 표시 없음 | 표시 없음 | 표시 없음 |
| degraded | 변경 없음 | 표시 없음 | 표시 없음 | 각주 (11px, #94a3b8) |
| critical | "[데이터 참고]" 프리픽스 | 표시 없음 | 인라인 마크 (11px) | 경고 각주 (11px, #94a3b8) |

### 7.2 개별 지표 처리

| validation_status | 표시 방식 |
|-------------------|----------|
| ok | 정상 표시 |
| anomaly | 수치를 "—" 처리, Footer 각주에 사유 |
| missing | 항목 자체 "데이터 없음" |
| previous_value | 수치 옆 "(전일)" 태그 (11px, 뮤트) |

핵심 원칙: 데이터 품질 알림은 어떤 상태에서든 눈에 띄는 배너, 경고 블록, 강조 색상을 사용하지 않는다. 항상 작은 각주 스타일을 유지하여 콘텐츠 읽기 경험을 최우선으로 보호한다.

## 8. 접근성 (요구사항 14)

- 모든 `<table>` 에 `role="presentation"` 유지
- `<html lang="ko">` 유지
- 색상 대비 WCAG 2.1 AA 준수 (본문 4.5:1, 큰 텍스트 3:1)
- 상승/하락 정보: 색상 + 방향 기호(▲/▼/—) 이중 전달
- 이모지 완전 제거 → HTML 엔티티 + CSS 인라인 스타일로 대체
- 터치 타겟 44px 확보 (모바일)

## 9. 호환성 전략 (요구사항 8)

### 9.1 CSS 전략

| 방법 | 용도 |
|------|------|
| 인라인 `style=""` | 모든 스타일의 1차 적용 (Gmail 안전) |
| `<style>` 블록 | 다크 모드, 반응형 미디어 쿼리만 |
| MSO 조건부 주석 | Outlook fallback (border-radius, gradient) |

### 9.2 금지 항목

- CSS `::before` / `::after` 가상 요소 (Outlook 미지원)
- SVG 인라인 (Outlook 미지원)
- 이모지 (클라이언트별 렌더링 차이)
- 명명된 HTML 엔티티 (숫자형 참조만 사용)

### 9.3 폰트 스택

```css
font-family: 'Apple SD Gothic Neo', 'Noto Sans KR', -apple-system,
  BlinkMacSystemFont, 'Malgun Gothic', 'Segoe UI', Roboto, sans-serif;
```

## 10. 기존 코드 변경 영향 분석

### 10.1 변경 파일 목록

| 파일 | 변경 유형 | 설명 |
|------|----------|------|
| `src/morning_brief/brief_formatting.py` | 대폭 수정 | LAYER 파싱 → Section 파싱, 새 타입 추가 |
| `src/morning_brief/emailer.py` | 대폭 수정 | `_build_email_context_v2()`, 새 빌더 함수들 |
| `src/morning_brief/prompts/brief_instructions.j2` | 전면 교체 | 3-LAYER → Section 0~6 구조 |
| `src/morning_brief/prompts/brief_input.j2` | 전면 교체 | LAYER 지시 → Section 지시 |
| `src/morning_brief/templates/email.html.j2` | 레거시 래퍼 | `email_base.html.j2` 로 리다이렉트 |
| `src/morning_brief/templates/email.txt.j2` | 수정 | 새 섹션 구조 반영 |
| `src/morning_brief/templates/email_*.html.j2` | 신규 (9개) | 파셜 + 매크로 파일 |

### 10.2 하위 호환성

- `extract_brief_structure()` 함수는 제거하지 않고 `extract_sections()` 로 내부 위임
- 기존 LAYER 구조 텍스트 감지 시 레거시 파싱으로 자동 폴백
- `render_briefing_email_html()` 공개 API 시그니처 유지
- `render_briefing_email_text()` 공개 API 시그니처 유지
- `build_briefing_message()` 공개 API 시그니처 유지
- `GmailSender.send()` 변경 없음

### 10.3 테스트 전략

| 테스트 유형 | 대상 | 도구 |
|------------|------|------|
| 단위 테스트 | `extract_sections()`, `parse_news_items()`, `parse_sector_mapping()`, `parse_event_calendar()` | pytest |
| 속성 기반 테스트 | 라운드트립 속성 (파싱 → 직렬화 → 재파싱) | hypothesis |
| 속성 기반 테스트 | 배지 방향 일관성 (양수→up, 음수→down, 0→flat) | hypothesis |
| 속성 기반 테스트 | 뉴스 아이템 파싱 (1~5개 항목, 필수 필드 존재) | hypothesis |
| 통합 테스트 | `_build_email_context_v2()` 전체 흐름 | pytest |
| 렌더링 테스트 | 각 파셜 독립 렌더링 | pytest + jinja2 |
| 스냅샷 테스트 | 전체 HTML 출력 비교 | pytest |

## 11. 정확성 속성 (Property-Based Testing)

### P1: 섹션 파싱 라운드트립

모든 유효한 SectionMap `m`에 대해:
```
extract_sections(serialize_sections(m)) == m
```
빈 섹션은 파싱 후에도 빈 문자열로 유지된다.

### P2: 배지 방향 일관성

모든 숫자 문자열 `v`에 대해:
- `float(v) > 0` → `direction == "up"`
- `float(v) < 0` → `direction == "down"`
- `float(v) == 0` → `direction == "flat"`

### P3: 뉴스 아이템 파싱 완전성

유효한 Section 4-2 텍스트(①~⑤ 포함)에 대해:
- `len(parse_news_items(text)) >= 1`
- 모든 아이템에 `headline` 이 비어있지 않음
- `number` 가 ①~⑤ 중 하나

### P4: 섹터 매핑 유효성

유효한 Section 4-3 텍스트에 대해:
- `parse_sector_mapping(text)` 가 None이 아니면, 3분류 모두 1개 이상 항목 존재
- 모든 항목에 `reason` 이 비어있지 않음

### P5: 공포탐욕 레이블 일관성

모든 정수 `v` (0~100)에 대해:
- `0 <= v <= 24` → `"Extreme Fear"`
- `25 <= v <= 49` → `"Fear"`
- `50 <= v <= 74` → `"Greed"`
- `75 <= v <= 100` → `"Extreme Greed"`
- `v >= 75` → `fear_greed_warning == "과열 경계"`

### P6: 데이터 품질 상태 일관성

모든 `data_quality_status` 에 대해:
- `status == "ok"` → `footer_notes` 가 빈 리스트
- `status == "critical"` → 메일 제목에 "[데이터 참고]" 포함
- `status != "ok"` → `footer_notes` 가 템플릿에 전달됨

### P7: 스냅샷 배지 개수

모든 유효한 packet에 대해:
- `len(snapshot_badges) <= 4`
- 각 배지에 `label`, `value`, `direction` 키 존재
- `direction` 은 "up", "down", "flat" 중 하나

## 12. 마이그레이션 계획

### 단계 1: 포맷터 + 데이터 모델 (brief_formatting.py)
- 새 타입 정의 (SectionMap, NewsItemV2 등)
- `extract_sections()` 구현
- `parse_news_items()`, `parse_sector_mapping()`, `parse_event_calendar()` 구현
- `serialize_sections()` 구현
- 기존 함수 하위 호환 유지

### 단계 2: 프롬프트 템플릿 (brief_instructions.j2, brief_input.j2)
- 3-LAYER → Section 0~6 구조 전환
- 문체 규칙 교체 (격식체 → 친근한 존댓말)
- 금융 용어 부연 설명 지시 추가
- 분량 제한 제거

### 단계 3: 이메일 빌더 (emailer.py)
- `_build_email_context_v2()` 구현
- 스냅샷 대시보드, BTC, 이벤트 빌더 추가
- 제목 생성 로직 추가
- 기존 `_build_email_context()` 는 `_v2` 로 내부 위임

### 단계 4: HTML 템플릿 파셜
- `email_macros.html.j2` (매크로)
- `email_base.html.j2` (마스터 레이아웃)
- `email_header.html.j2`, `email_hero.html.j2`, `email_news.html.j2`
- `email_btc.html.j2`, `email_market.html.j2`
- `email_sector.html.j2`, `email_calendar.html.j2`
- `email_footer.html.j2`
- 기존 `email.html.j2` → `email_base.html.j2` 리다이렉트

### 단계 5: 텍스트 템플릿 + 통합 테스트
- `email.txt.j2` 업데이트
- 전체 파이프라인 통합 테스트
- 속성 기반 테스트 (P1~P7)
- `make check` 통과 확인
