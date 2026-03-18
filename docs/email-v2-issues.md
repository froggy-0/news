# V2 이메일 템플릿 이슈 목록

`docs/email.log` 기준 실제 수신 메일을 검토한 결과입니다.

---

## 1. 오늘의 핵심 (hero_summary) — 글자 크기 과대

`email_hero.html.j2`에서 `hero_summary` 전체를 `font-size:32px; font-weight:800`으로 렌더링한다.
Section 0에는 핵심 판단 한 줄 + 환율 알림 + 코스피 영향 설명 등 여러 문장이 들어오는데, 전부 32px로 출력되어 가독성이 떨어진다.

- 현재: `hero_summary` 전체 → 32px
- 기대: 첫 문장(핵심 판단)만 32px, 나머지 보조 문장은 14~15px body 크기

## 2. 핵심 뉴스 전부 영어

5개 뉴스 항목(①~⑤) 모두 영어 헤드라인·본문·tldr이다.
`brief_instructions.j2` 프롬프트에서 한국어 헤드라인을 요구하지만 LLM이 따르지 않고 있다.
`parse_news_items()`는 LLM 출력을 그대로 파싱하므로 번역 로직이 없다.

- 원인: LLM 프롬프트 준수 실패 또는 프롬프트 지시 강도 부족
- 영향: `tldr` 필드도 영어 헤드라인을 그대로 반복

## 3. 뉴스 본문 텍스트 중복

각 뉴스 항목의 body 텍스트가 동일 내용으로 2회 반복된다.
예: ② SEC Chairman 항목 — "Direct official confirmation…" 단락이 두 번 출력.

- 원인: LLM이 같은 단락을 두 번 생성한 것으로 추정
- 대응: `parse_news_items()`에서 중복 단락 제거 로직 추가 검토 필요

## 4. 시장 지표 섹션 비어있음

"■ 시장 지표" 헤더와 푸터만 표시되고 `stock_indices`, `stock_tech`, `macro_indicators` 모두 비어있다.

가능한 원인 두 가지:

1. `extract_sections()`가 section_1(거시 지표), section_2(미국 증시)를 추출하지 못함
   - LLM 출력에 `## 1.` / `## 2.` 형식의 섹션 헤딩이 없으면 `SECTION_HEADING_V2_RE`가 매칭 실패
2. 파싱 함수가 LLM 출력 포맷과 불일치
   - `_parse_macro_indicators()`: `라벨: 값 (변동)` 패턴 기대 — LLM이 다른 포맷으로 출력하면 빈 리스트
   - `_parse_stocks()`: `TICKER $가격 ±변동%` 패턴 기대 — 마찬가지

시장 지표 데이터는 `packet`에 이미 존재하므로(snapshot_badges에서 S&P 500, 나스닥, VIX 등 정상 표시), LLM 텍스트 파싱 대신 `packet` 데이터를 직접 사용하는 방안도 검토 가능.

## 5. 섹터 매핑 섹션 누락

"오늘 주목 흐름" 섹션이 메일에 없다.
`email_base.html.j2`에서 `{% if sector_mapping %}` 가드로 보호되어 있어, `parse_sector_mapping(section_4_3)`이 빈 값을 반환한 것으로 보인다.

- 원인: section_4_3 추출 실패 또는 LLM이 해당 섹션을 생성하지 않음

## 6. 이벤트 캘린더 섹션 누락

캘린더 섹션이 메일에 없다.
`{% if event_calendar %}` 가드 → `parse_event_calendar(section_6)` 빈 값 반환.

- 원인: section_6 추출 실패 또는 LLM이 해당 섹션을 생성하지 않음

## 7. BTC ETF 합산 거래량 $0

`etf_total_volume`이 "$0"으로 표시된다.

```python
# _build_btc_data()
sum(e.get("volume", 0) for e in btc.get("etf_points", []))
```

`etf_points`는 `MarketPoint` dict 리스트인데, `MarketPoint`에는 `volume` 필드가 없다.
(`price`, `change_pct`, `label`, `ticker`, `canonical_key` 등만 존재)
→ 항상 default 0으로 합산되어 $0.

## 8. BTC ETF 등락 표시 이상

각 ETF 행의 등락 컬럼에 `— -3.26` 형태로 표시된다.

`email_btc.html.j2`에서 `badge(etf.change_pct, etf.direction)` 매크로를 호출하는데,
`etf_items`에 `MarketPoint` dict가 그대로 전달된다.

- `etf.change_pct` → `MarketPoint.change_pct`는 float (예: `-3.26`)
- `etf.direction` → `MarketPoint`에 `direction` 키 없음 → `default('flat')` → 항상 `—`
- `badge()` 매크로는 `"+1.2%"` 같은 포맷된 문자열을 기대

필요 조치: `_build_btc_data()`에서 `etf_points`를 ETF 표시용 dict로 변환해야 함 (direction 계산, change_pct 포맷팅).

## 9. 기관 보유 현황 데이터 불완전

```
Bitwise BITB — BTC · AUM
iShares IBIT — BTC · AUM
```

BTC 보유량과 AUM 값이 비어있다.

`email_btc.html.j2` 템플릿:
```
{{ snap.btc_held }} BTC · AUM {{ snap.aum }}
```

`BitcoinEtfIssuerSnapshot` 모델 필드:
- `total_btc` (템플릿은 `btc_held` 참조)
- `aum_usd` (템플릿은 `aum` 참조)

필드명 불일치로 값이 렌더링되지 않는다.

## 10. display_date 비어있음

헤더에 날짜 없이 `· 3분 읽기`만 표시된다.

```python
# _format_display_date_v2()
date_str = packet.get("date", "")
```

`packet`에 최상위 `date` 키가 없으면 빈 문자열 반환.
파이프라인에서 `packet["date"]`를 설정하는지 확인 필요.

---

## 우선순위 제안

| 우선순위 | 이슈 | 이유 |
|---------|------|------|
| P0 | #4 시장 지표 비어있음 | 핵심 섹션 전체 누락 |
| P0 | #2 뉴스 전부 영어 | 한국어 브리핑의 핵심 가치 훼손 |
| P1 | #7 ETF 거래량 $0 | 잘못된 데이터 표시 |
| P1 | #8 ETF 등락 표시 이상 | 잘못된 데이터 표시 |
| P1 | #9 기관 보유 현황 불완전 | 필드명 불일치 — 단순 수정 |
| P1 | #10 날짜 누락 | 헤더 정보 누락 |
| P2 | #1 hero 글자 크기 | UX 개선 |
| P2 | #3 뉴스 본문 중복 | LLM 출력 품질 이슈 |
| P2 | #5 섹터 매핑 누락 | 섹션 추출 또는 LLM 출력 이슈 |
| P2 | #6 캘린더 누락 | 섹션 추출 또는 LLM 출력 이슈 |
