# 파이프라인 실행 진단 리포트

대상 실행: `Run #23189927703` (2026-03-17 19:33 KST, main 브랜치)
최종 상태: `ok` (성공) — 하지만 아래 문제들이 존재

---

## 요약

| 심각도 | 문제 | 영향 |
|---|---|---|
| 🔴 높음 | 달러 인덱스(DXY) 수집 완전 실패 | 거시 지표 5종 중 1종 누락, 브리핑에 DXY 정보 없음 |
| 🔴 높음 | BTC ETF 공식 스냅샷 Perplexity 응답 빈 배열 | direct fetch fallback으로 2건만 수집, 3건 누락 |
| 🟡 중간 | 뉴스 토픽 커버리지 2/4 | macro, us_equity 토픽 뉴스 없음 |
| 🟡 중간 | 브리핑 검수 실패 후 재작성해도 미통과 | 구조 불완전(LAYER 3 잘림), 반복 표현, 형식 불일치 |
| 🟡 중간 | Grok X 키워드 macro_and_equity 0건 | 거시/주식 실시간 시그널 수집 실패 |
| 🟡 중간 | GitHub Actions 캐시 save 전부 실패 | 같은 날 키로 이미 저장됨 → 다음 실행에 영향 없지만 갱신 불가 |
| 🟠 낮음 | yfinance 실패율 50% (6요청 중 3성공, 1실패, 2재시도) | DXY 외 나머지는 Stooq에서 성공 |
| 🟠 낮음 | Node.js 20 deprecation 경고 | 2026-06-02부터 강제 Node.js 24 전환 예정 |

---

## 1. 🔴 달러 인덱스(DXY) 수집 완전 실패

```
10:34:24 | ERROR | yfinance | $DX-Y.NYB: possibly delisted; no price data found (period=7d)
10:34:25 | WARNING | yfinance 데이터를 다시 가져오는 중이에요 (1/3). 대상=DX-Y.NYB
10:34:25 | ERROR | yfinance | $DX-Y.NYB: possibly delisted; no price data found (period=7d)
10:34:25 | WARNING | yfinance 데이터를 다시 가져오는 중이에요 (2/3). 대상=DX-Y.NYB
10:34:27 | ERROR | yfinance | $DX-Y.NYB: possibly delisted; no price data found (period=7d)
10:34:27 | WARNING | 달러 인덱스 (DX-Y.NYB) 데이터를 바로 가져오지 못해 비워둘게요
```

원인:
- DXY는 FRED에 없고 yfinance `DX-Y.NYB`만 사용 (Stooq 경로 없음)
- yfinance가 "possibly delisted"로 3회 재시도 후 포기
- 캐시에도 이전 성공 값이 없어 `validation_status=missing`으로 최종 생략

결과:
- `market_anomalies`에 `dxy` 기록: `"원본 데이터와 마지막 성공 값이 모두 없어 생략했어요."`
- 브리핑에 달러 인덱스 정보 완전 누락

개선 방향:
- DXY에 Stooq fallback 추가 (예: `dx.f` 또는 `usdx.us`) 또는 FRED broad dollar index 대안 검토
- 또는 yfinance 티커를 `DX=F` (달러 선물)로 변경 시도

---

## 2. 🔴 BTC ETF 공식 스냅샷 Perplexity 빈 응답

```
10:34:58 | btc_etf_reference_parse_empty | response_preview: "{ \"snapshots\": [] }" | source_domain_count: 3
10:34:58 | INFO | Perplexity ETF 참조 스냅샷이 비어 공식 발행사 페이지를 직접 다시 볼게요.
10:34:59 | btc_etf_reference_direct_fetch | snapshot_count: 2 | failures: []
```

원인:
- Perplexity structured query가 3개 issuer 도메인을 참조했지만 빈 `snapshots` 배열 반환
- direct fetch fallback으로 2건만 성공 (IBIT/BITB/GBTC 중 1건 누락 추정)

결과:
- `official_btc_etf` provider: 2 requests, 2 successes — 하지만 3개 ETF 중 2개만 데이터 확보
- 일일 순유입 계산이 불완전할 수 있음

개선 방향:
- Perplexity 빈 응답 시 direct fetch를 3개 ETF 모두에 대해 시도하는지 확인
- direct fetch 성공 2건의 구체적 티커 로깅 추가

---

## 3. 🟡 뉴스 토픽 커버리지 2/4

```
10:36:02 | INFO | Perplexity와 공식 시그널만으로도 기사 5건, 도메인 5개, 토픽 2개 기준을 채웠어요.
10:36:02 | INFO | 최종 뉴스 구성은 Perplexity 1건, 공식 시그널 4건, legacy 0건
         | provider 비중 {'grok_official_x': 4, 'perplexity_sonar': 1}
```

문제:
- 4개 토픽(macro, ai_bigtech, bitcoin, us_equity) 중 2개만 커버
- Sonar에서 4개 토픽 모두 요약은 수집했지만, 최종 뉴스 5건에는 2개 토픽만 포함
- Perplexity 뉴스 1건 + Grok 공식 X 4건 = 5건으로 `MAX_NEWS_ITEMS=5` 충족 → legacy fallback 미발동
- 하지만 macro, us_equity 토픽 뉴스가 없어 브리핑의 해당 섹션이 빈약할 수 있음

원인:
- Grok 공식 X 4건이 ai_bigtech/bitcoin 위주 (NVIDIA GTC, crypto inflows)
- Grok X 키워드 `macro_and_equity` 그룹이 0건 반환
- `MAX_NEWS_ITEMS=5`가 너무 작아 토픽 다양성 확보 어려움

개선 방향:
- 토픽 커버리지가 3 미만이면 legacy fallback 발동 조건 추가 검토
- 또는 `MAX_NEWS_ITEMS`를 7~8로 상향

---

## 4. 🟡 브리핑 검수 실패 (재작성 후에도 미통과)

```
10:37:00 | WARNING | 브리핑 최종 검수에서 보완점을 찾았어요:
  - 구조 불완전: LAYER 3이 중간에 잘려 'SOXX는 반도체 섹'으로 끝남
  - LAYER 1 규칙 위반: 결론 반복 문제
  - LAYER 2 형식 위반: 항목별 구분 일관성 부족

10:37:21 | INFO | 검수 지적을 반영해 브리핑을 1회 다듬었어요.

10:37:32 | WARNING | 재작성 뒤에도 보완점이 남아 있어요:
  - LAYER 1 중복 성격 문장
  - LAYER 2 단정적 표현
  - LAYER 3 BTC 숫자 표기 표준화 필요
```

원인:
- `OPENAI_MAX_OUTPUT_TOKENS=2300`이 LAYER 3까지 완성하기에 부족 → 중간 잘림
- 재작성 1회(`OPENAI_BRIEF_MAX_REWRITES=1`)로는 구조 문제 해결 불가

결과:
- `brief_review_failed` 이벤트 기록
- 하지만 `data_quality`가 `ok`이므로 이메일은 발송됨 (critical + 검수 미통과 조합만 skip)
- 불완전한 브리핑이 수신자에게 전달됨

개선 방향:
- `OPENAI_MAX_OUTPUT_TOKENS`를 2500~2800으로 상향 (LAYER 3 잘림 방지)
- 또는 프롬프트에서 LAYER 3 분량 가이드 강화

---

## 5. 🟡 Grok X 키워드 macro_and_equity 0건

```
10:35:47 | INFO | Grok X Search macro_and_equity: 0건 시그널 수집
10:35:54 | INFO | Grok X Search crypto_and_etf: 6건 시그널 수집
10:35:59 | INFO | Grok X Search ai_bigtech_primary: 4건 시그널 수집
10:36:02 | INFO | Grok X Search btc_etf_primary: 0건 시그널 수집
```

- 4개 그룹 중 2개(macro_and_equity, btc_etf_primary)가 0건
- macro 관련 X 시그널이 없어 거시 토픽 뉴스 부재에 기여
- btc_etf_primary도 0건이지만 crypto_and_etf에서 6건 수집으로 보완

---

## 6. 🟡 GitHub Actions 캐시 save 전부 실패

```
10:37:33 | Failed to save: Unable to reserve cache with key btc-etf-snapshots-20260317
10:37:34 | Failed to save: Unable to reserve cache with key market-snapshot-20260317
10:37:35 | Failed to save: Unable to reserve cache with key pip-d32246a4241e71dee9763c6a69c2bd527198c46029e291eb6444752e4460ad27
```

원인:
- 같은 날짜 키로 이전 실행(04:48 UTC)에서 이미 저장됨
- GitHub Actions 캐시는 같은 키로 덮어쓰기 불가 (immutable)
- 이번 실행(10:33 UTC)은 restore는 성공했지만 save는 키 충돌로 실패

영향:
- 이번 실행에서 갱신된 ETF 스냅샷/시장 데이터가 캐시에 반영되지 않음
- 다음 날 실행에서는 새 날짜 키를 사용하므로 직접적 문제는 없음
- 하지만 같은 날 여러 번 실행 시 첫 실행의 캐시만 유지됨

개선 방향:
- 캐시 키에 시간 단위 추가 (예: `btc-etf-snapshots-20260317-1033`) + restore-keys prefix 유지
- 또는 현재 동작을 의도된 것으로 수용 (하루 1회 실행 기준)

---

## 7. 🟠 yfinance 실패율

```
yfinance: requests=6, successes=3, failures=1, retries=2
```

- 6건 요청 중 3건 성공, 1건 실패(DXY), 2건 재시도 소모
- DXY 외 나머지 yfinance 요청(환율, 선물 등)은 성공
- Stooq가 18건 전부 성공하여 주요 지표는 커버됨

---

## 8. 실행 시간 분석

| Phase | 소요 시간 | 비고 |
|---|---|---|
| market | 36.2초 | DXY 재시도 3회(~4초) + BTC ETF Perplexity + direct fetch |
| news | 62.7초 | Sonar 4토픽(~26초) + Grok 공식(~15초) + Grok 키워드(~17초) |
| brief | 35.8초 | OpenAI 브리핑 생성 |
| review | 42.8초 | 검수(10.9초) + 재작성(21.2초) + 재검수(10.6초) |
| backfill | 0초 | 스킵 |
| email | 1.0초 | |
| **총합** | **189.9초** (~3분 10초) | |

review가 전체의 22%를 차지하며, 재작성 후에도 미통과 → 시간 낭비 요소

---

## 9. 비용 분석

| Provider | 요청 수 | 비용 |
|---|---|---|
| OpenAI | 4 | $0.0208 |
| Grok keyword | 4 | $0.0113 |
| Grok official | 4 | $0.0087 |
| Perplexity | 6 | $0.0046 |
| **합계** | **18** | **$0.0455** |

OpenAI 4건 = 브리핑 생성 1 + 검수 1 + 재작성 1 + 재검수 1
→ 검수 미통과에도 재작성+재검수로 2건 추가 비용 발생

---

## 10. 정상 동작 확인 항목

| 항목 | 상태 |
|---|---|
| FRED 거시 지표 (us10y, us2y, vix) | ✅ 3건 성공 |
| Stooq 시장 데이터 (지수+기술주+ETF) | ✅ 18건 전부 성공 |
| CoinGecko BTC 현물 | ✅ 성공 |
| Fear & Greed Index | ✅ 성공 |
| Perplexity Sonar 4토픽 요약 | ✅ 전부 성공 |
| Perplexity Sonar 맥락 분석 | ✅ analyses=3, narrative 생성 |
| Grok 공식 X 시그널 | ✅ 4건 수집 |
| 캐시 restore (btc_etf, market, pip) | ✅ 3건 모두 primary_hit |
| 품질 게이트 (format, lint, test) | ✅ 전부 통과 |
| Gmail 발송 | ✅ 1명 발송 완료 |
| Artifact 업로드 | ✅ 4파일 업로드 |
