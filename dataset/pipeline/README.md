# CoinDesk 뉴스 데이터셋 파이프라인

CoinDesk Data API를 이용해 암호화폐 뉴스를 수집·정제·분류하는 로컬 파이프라인입니다.

---

## 빠른 시작

```bash
# 프로젝트 루트에서 실행
python dataset/collect.py collect          # 1. 수집 (2013-01-01 ~ 오늘)
python dataset/collect.py process          # 2. 정제 (RSS 꼬리말 제거)
python dataset/collect.py split            # 3. 카테고리별 분기 (선택)
python dataset/collect.py status          # 4. 현황 확인
```

---

## API 스펙 (실측 기반)

| 항목 | 값 |
|------|-----|
| 엔드포인트 | `https://data-api.coindesk.com/news/v1/article/list` |
| 인증 | **없음** (완전 공개 API) |
| 최대 `limit` | **100** (150 이상은 HTTP 400 반환, 공식 문서상 50이지만 실제 100 작동) |
| 페이지네이션 | `to_ts` 커서 방식 (역방향) — `page` 파라미터는 오프셋 없이 동일 데이터 반환 |
| 역사 범위 | 2013년 초부터 현재까지 |
| Rate limit 헤더 | **없음** (공식 명시 없음, X-CryptoCompare 인프라 사용 확인) |
| 응답 형식 | `{"Data": [...], "Err": {}}` |

### 주요 쿼리 파라미터

| 파라미터 | 타입 | 설명 |
|---------|------|------|
| `lang` | string | 언어 필터 (`EN` 고정) |
| `limit` | int | 페이지당 기사 수 (최대 100) |
| `to_ts` | int | Unix timestamp (이 시각 이전 기사 반환, inclusive) |
| `from_ts` | int | Unix timestamp (이 시각 이후 기사 필터, `to_ts`와 병용 가능) |
| `categories` | string | 카테고리 필터 (`,` 구분, 미사용 시 전체) |

---

## 수집 가능한 기사 범위

### 하루치 기사를 누락 없이 수집하는가?

**YES.** `to_ts` 커서를 이용한 역방향 페이지네이션으로 하루 전체를 완전히 수집합니다.

```
[하루 수집 흐름]

cursor = day_end (23:59:59 UTC)

while True:
    GET ?to_ts=cursor&limit=100
    → 최신 순으로 최대 100건 반환

    start_ts 이전 기사 등장 시 루프 종료
    cursor = min(published_on) - 1   ← to_ts inclusive 이므로 -1 필수
    sleep(delay_seconds)
```

하루 기사 수가 많은 날(2024년 기준 최대 ~500건)도 `limit=100`으로 5~6 페이지면 커버됩니다.  
일일 수집 건수에 API 측 상한은 없습니다.

### 수집 방향

**최신 → 과거** 순으로 수집합니다. 수집을 중단하더라도 최근 데이터부터 쌓이므로, 완전한 역사 데이터가 필요하지 않은 경우 조기 중단해도 됩니다.

### 연도별 규모 (실측 기반)

| 연도 | 하루 평균 | pages/day | 연간 기사 | 비고 |
|------|---------|---------|---------|------|
| 2013~2019 | 6~50건 | 2 | ~3,000~18,000건 | 초창기~성장기 |
| 2020~2021 | 90~100건 | 2 | ~33,000건 | |
| 2022~2023 | 200~250건 | 3~4 | ~73,000~91,000건 | |
| 2024~2026 | 280~320건 | 4~5 | ~100,000건 | 현재 |
| **전체** | | **~12,600 pages** | **~534,000건** | 2013~2026 |

---

## IP 차단 및 Rate Limit 위험 분석

### 공식 제한 정보

CoinDesk/CryptoCompare Data API는 현재(2026년 4월 기준) **공식 rate limit을 응답 헤더에 노출하지 않습니다.**  
문서 사이트가 JavaScript SPA로 렌더링되어 스크래핑 불가하나, 실측으로 다음을 확인했습니다.

| 측정 항목 | 결과 |
|---------|------|
| 연속 10회 즉시 요청 | 모두 200 OK (13.3초, 평균 0.75s/req) |
| 429 응답 확인 여부 | 테스트 범위 내 미발생 |
| Rate limit 헤더 | X-CryptoCompare-Cache-Hit 외 없음 |

### 위험도 평가

```
속도          위험도    설명
─────────────────────────────────────────────────────
0.3s (3.3/s)  ⚠️  중간   공개 API 기준 다소 빠름, 단시간 집중 수집 시 주의
0.5s (2.0/s)  ✅  낮음   권장 기본값. 일반적인 공개 API 안전 범위
1.0s (1.0/s)  ✅  매우낮음 확실한 안전, 전체 수집 시간 ~2배
```

### 예상 소요 시간 (2013-01-01 ~ 현재, 실측 3.2s/page 기준)

| delay | req/s | 예상 시간 | 비고 |
|-------|-------|---------|------|
| `0.3s` | 3.3/s | **~7시간** | 빠름, 모니터링 필수 |
| `0.5s` | 2.0/s | **~11시간** | 권장 기본값 |
| `1.0s` | 1.0/s | **~20시간** | 보수적, 야간 실행 적합 |

총 API 요청 약 12,600회, 약 534,000건 수집 예상.

```bash
# 기본 (권장) — 약 11시간
python dataset/collect.py collect --delay 0.5

# 보수적 (야간 tmux/nohup) — 약 20시간
python dataset/collect.py collect --delay 1.0

# 빠른 수집 (모니터링 필수) — 약 7시간
python dataset/collect.py collect --delay 0.3
```

### 안전 가이드라인

1. **User-Agent 설정**: 파이프라인이 식별 가능한 User-Agent를 자동으로 전송합니다
2. **지수 백오프**: 429/5xx 응답 시 최대 60초까지 자동 대기 후 재시도
3. **체크포인트**: 중단 재시작으로 동일 날짜 중복 요청 방지
4. **새벽 시간대 실행 권장**: 트래픽이 적은 시간대 (`nohup` 또는 `tmux` 활용)

---

## 디렉토리 구조

```
dataset/
├── collect.py          ← CLI 진입점
├── pipeline/
│   ├── checkpoint.py   ← SQLite 체크포인트 (수집/처리 상태 추적)
│   ├── fetcher.py      ← API 수집 로직
│   ├── processor.py    ← RSS 제거 등 전처리
│   ├── splitter.py     ← raw → by_category 분기
│   └── writer.py       ← 원자적 JSONL 쓰기
│
└── data/               (.gitignore)
    ├── raw/                    ← 원본 (불변)
    │   └── YYYY/MM/YYYY-MM-DD.jsonl
    ├── processed/              ← 정제 사본 (ML 학습용)
    │   └── YYYY/MM/YYYY-MM-DD.jsonl
    ├── by_category/            ← raw 파생 카테고리 뷰
    │   └── CATNAME/YYYY/MM/YYYY-MM-DD.jsonl
    └── _meta/
        ├── checkpoint.db       ← 수집/처리 완료 이력 (SQLite)
        └── dataset.json        ← 데이터셋 전체 메타정보
```

---

## JSONL 레코드 스키마

### raw/ 레코드 (v1)

```json
{
  "_schema_version": "1",
  "id": "21950171",
  "guid": "coindesk-abc123",
  "title": "Bitcoin Hits New ATH",
  "subtitle": "Markets rally as institutional demand surges",
  "body": "Full article text...",
  "title_char_count": 22,
  "body_char_count": 1840,
  "has_body": true,
  "authors": ["Alice Smith", "Bob Jones"],
  "categories": ["BTC", "MARKET", "TRADING"],
  "keywords": "BTC|ETH|MARKET",
  "sentiment": "POSITIVE",
  "score": 142.5,
  "upvotes": 48,
  "downvotes": 3,
  "url": "https://www.coindesk.com/markets/...",
  "source": "CoinDesk",
  "published_at": "2024-01-15T10:30:00Z",
  "published_ts": 1705312200,
  "created_on": 1705311000,
  "updated_on": 1705315800,
  "date": "2024-01-15",
  "_collected_at": "2026-04-26T12:00:00Z"
}
```

### processed/ 추가 필드

```json
{
  "body": "(RSS 꼬리말 제거된 본문)",
  "body_char_count": 1720,
  "_cleaning_ops": ["rss_suffix", "whitespace"],
  "_processed_at": "2026-04-26T13:00:00Z"
}
```

---

## 서브커맨드 레퍼런스

### `collect` — API 수집

```
python dataset/collect.py collect [옵션]

옵션:
  --start YYYY-MM-DD   수집 시작일 (기본: 2013-01-01)
  --end   YYYY-MM-DD   수집 종료일 (기본: 오늘)
  --delay SEC          요청 간 딜레이 초 (기본: 0.5, 권장 최소: 0.5)
  --force              완료된 날짜도 재수집
```

### `process` — 전처리

```
python dataset/collect.py process [옵션]

적용 정제 작업:
  rss_suffix    "appeared first on X." 꼬리말 제거
  whitespace    연속 공백/줄바꿈 정규화

옵션:
  --force       이미 처리된 날짜도 재처리
```

### `split` — 카테고리 분기

```
python dataset/collect.py split [옵션]

분기 카테고리 (19개):
  코인: BTC ETH XRP SOL BNB ADA DOGE AVAX
  시장: MARKET TRADING EXCHANGE ALTCOIN
  산업: REGULATION BLOCKCHAIN MINING TECHNOLOGY
  거시: MACROECONOMICS RESEARCH CRYPTOCURRENCY

옵션:
  --force       기존 파일 덮어쓰기
```

### `status` — 현황 확인

```
python dataset/collect.py status
```

---

## 중단 후 재시작

파이프라인은 SQLite 체크포인트(`_meta/checkpoint.db`)를 사용하여 완료된 날짜를 기록합니다.  
중단 후 동일 커맨드를 재실행하면 완료된 날짜를 자동으로 건너뛰고 이어서 수집합니다.

```bash
# 중단된 수집 재개 (별도 옵션 불필요)
python dataset/collect.py collect

# 특정 날짜를 강제 재수집
python dataset/collect.py collect --start 2020-03-01 --end 2020-03-31 --force
```

---

## 데이터 레이어 관계

```
CoinDesk API
     │
     ▼
  raw/              ← 원본 보존 (수정 금지)
     │
     ├──▶ processed/    collect.py process
     │        RSS 제거, 공백 정규화
     │
     └──▶ by_category/  collect.py split
              카테고리별 파생 뷰 (raw 기사 중복 포함 가능)
```

**ML 학습 시 `processed/` 사용을 권장합니다.**  
`raw/`는 재처리 기준점으로 보존하고 직접 수정하지 마세요.

---

## sentiment 레이블 주의사항

API가 제공하는 `sentiment` 필드(`POSITIVE` / `NEUTRAL` / `NEGATIVE`)는 CoinDesk/CryptoCompare가
자체적으로 부여한 레이블입니다.

- 2024-01-15 기준 분포: POSITIVE 55% / NEUTRAL 28% / NEGATIVE 17%
- 레이블 정의 및 방법론이 공개되지 않음 (키워드 기반 추정)
- BERT 파인튜닝의 **weak supervision**으로는 활용 가능하나 ground truth로 신뢰하지 말 것
- 연도별로 레이블 기준이 바뀌었을 가능성 있음 → 시계열 분석 시 검증 필요

---

## 알려진 데이터 품질 이슈

| 이슈 | 빈도 | 처리 방법 |
|------|------|---------|
| RSS 배포 꼬리말 (`appeared first on X.`) | 약 26% | `process` 커맨드로 제거 |
| body 없는 기사 (헤드라인만) | 약 10% | `has_body=False` 필드로 식별 |
| 동일 날짜 내 중복 기사 ID | < 1% | 수집 중 in-flight dedup |
| body 100자 미만 short blurb | 약 10% | `body_char_count` 필드로 필터링 |
