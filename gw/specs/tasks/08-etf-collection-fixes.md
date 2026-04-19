# ETF 수집 실패 및 부분 합산 문제

> Grayscale 429 rate limit으로 GBTC/BTC Mini 수집 실패, 브리핑에 불완전한 합산값 노출

---

## 현상 (2026-04-15 로그)

```
etf.primary_source_failed | GBTC  | HTTP 429 (etfs.grayscale.com/gbtc)
etf.primary_source_failed | BTC   | HTTP 429 (etfs.grayscale.com/btc)
etf.primary_source_failed | FBTC  | 기준일을 찾지 못했어요
```

5개 issuer 중 **IBIT, BITB만 성공**, GBTC/BTC Mini/FBTC 실패.

---

## 영향 범위

### 브리핑 경로 (`market.py`)

```python
# _summarize_official_btc_etf_snapshots
total_btc = sum(snapshot.total_btc for snapshot in primary_snapshots)
```

성공한 issuer만 합산하고 **몇 개 중 몇 개인지 표시하지 않음**. IBIT+BITB 합산이 `official_etf_total_btc`로 들어가서 사용자는 전체 시장 보유량으로 오해할 수 있음.

### sentiment-join 경로 (`etf_flows.py`)

```python
ETF_ANALYSIS_TICKERS = ("IBIT", "BITB")  # GBTC 아예 안 봄
```

sentiment-join은 처음부터 IBIT+BITB만 사용하므로 **GBTC 실패와 무관**. 다만 시장 커버리지가 ~70%로 제한됨.

---

## 원인

### 1. Grayscale rate limit

`etfs.grayscale.com`이 429를 반환. 현재 provider 설정:

```python
# provider_runtime.py
"btc_etf_official": ProviderPolicy(
    min_interval_seconds=0.25,  # 250ms 간격
    base_backoff_seconds=1.0,
    max_attempts=3,
)
```

GBTC → BTC Mini 순서로 같은 도메인에 연속 요청하면서 rate limit에 걸림.

### 2. FBTC 파서 깨짐

`digital.fidelity.com` 페이지 구조가 변경되어 기준일 파싱 실패. HTML fallback도 실패.

### 3. 부분 합산 경고 없음

`_summarize_official_btc_etf_snapshots`가 성공한 것만 합산하지만, 몇 개가 빠졌는지 반환하지 않음.

---

## 수정 방안

### A. Grayscale rate limit 대응

`min_interval_seconds`를 늘리거나, 같은 도메인 요청 사이에 추가 대기:

```python
"btc_etf_official": ProviderPolicy(
    min_interval_seconds=1.0,   # 250ms → 1초로 증가
    base_backoff_seconds=2.0,
    max_attempts=4,
)
```

### B. 부분 합산 시 커버리지 메타데이터 추가

```python
def _summarize_official_btc_etf_snapshots(snapshots):
    ...
    return (
        round(total_btc, 8),
        round(total_aum_usd, 2),
        len(primary_snapshots),  # 성공 issuer 수
        len(ALL_TICKERS),        # 전체 issuer 수
    )
```

브리핑/공개 산출물에 "5개 중 2개 issuer 기준" 같은 주석을 남길 수 있음.

### C. FBTC 파서 점검

`parse_fbtc_snapshot`이 현재 `digital.fidelity.com` 페이지 구조와 맞는지 확인 필요. HTML 구조 변경 시 파서 업데이트.

### D. sentiment-join ETF 커버리지 문서화

`ETF_ANALYSIS_TICKERS = ("IBIT", "BITB")`가 시장의 ~70%만 커버한다는 점을 리포트 한계 섹션에 명시.

---

## 수정 대상 파일

| 파일 | 변경 |
|---|---|
| `provider_runtime.py` | `btc_etf_official` min_interval 증가 |
| `market.py` | `_summarize_official_btc_etf_snapshots` 반환값에 커버리지 정보 추가 |
| `btc_etf_official.py` | FBTC 파서 점검/수정 |
| `report-draft.md` | 연구 한계에 ETF 커버리지 ~70% 명시 |

---

## 추가: SPY 검증 범위 상한 초과

### 현상

```json
"raw_value": 700.2277,
"resolved_value": null,
"resolution_reason": "원본 값 700.23가 허용 범위(300~700)를 벗어나 생략했어요."
```

`market_policy.py`의 `MARKET_VALIDATION_BOUNDS`에서 SPY 상한이 700으로 설정되어 있어, 실제 시세($700.23)가 anomaly로 제외됩니다.

### 수정

```python
# market_policy.py
"spy": (300.0, 900.0),  # 700 → 900 (시장 성장 반영)
```

QQQ, SOXX는 검증 범위가 아예 없으므로 함께 추가하는 것도 고려:

```python
"qqq": (200.0, 1000.0),
"soxx": (100.0, 800.0),
```

### 수정 대상

| 파일 | 변경 |
|---|---|
| `market_policy.py` | `MARKET_VALIDATION_BOUNDS`의 `spy` 상한 900으로 변경, `qqq`/`soxx` 범위 추가 |
