# 데이터 수집 파이프라인 감사 리포트 (2026-07-24)

> **범위**: 뉴스 원문 수집 → 감성분석 → 센티먼트 조인(sentiment_join) → 아레나 기술적 지표 수집까지
> 전 수집 경로를 코드베이스 기준으로 감사. 문제·개선점·데이터 유의미성·가중치 타당성·신뢰성을 점검.
> **방법**: 실제 소스 코드 정독(파일:라인 근거 첨부). 실행/네트워크 테스트는 미포함(정적 분석).
> **결론 요약**: 구조·방어 로직은 견고. 단 **뉴스 감성 집계 가중치 부재**(가장 실질적 결함)와
> **미구현 스캐폴딩 방치**, **일부 스케일링/통계 처리의 미세 결함**이 개선 후보.

---

## 0. 두 개의 독립 수집 경로 (재확인)

| 경로 | 실행 | 소스 | 산출물 |
|---|---|---|---|
| **A. 뉴스+매크로 조인** (`sentiment_join`) | 매일 KST 07:40 (`morning-brief.yml`) | THENEWSAPI→FinBERT, FNG, VIX, Binance, KIS, 선물, ETF, breadth, stablecoin | `latest.json`(R2), `master_*.parquet` |
| **B. 아레나 기술지표** (`arena`) | 4시간마다 (EC2 `scheduler.py`) | Binance klines(현물·선물) | Supabase `arena_*` 테이블 |

두 경로는 **R2 `latest.json`을 매개로 단방향 연결**(A가 산출 → B가 macro로 fetch). B의 기술지표(RSI/MACD 등)는
A와 무관하게 직접 계산되고, A의 리스크오버레이만 macro 게이트로 주입됨(`scheduler.py:669`).

---

## 1. 가중치(Weights) 타당성 분석

### 1.1 ✅ 견고 — PCA 기반 데이터 주도 가중치
하이브리드 지수·서브지수는 **손으로 튜닝한 가중치가 없다**. PCA loadings가 데이터에서 자동 추출됨.

- `hybrid_index.py:466-490`: PC1 loadings = 가중치. VIF gate(threshold 10.0, `hybrid_index.py:61`)로 공선성 자동 제거.
- **부호 고정**: `HYBRID_SIGN_ANCHOR = "fng_value_lag1"`(`hybrid_index.py:60`, `479-484`) — full/core 두 지수 방향 통일. 합리적.
- **full/core 이중화**(`hybrid_index.py:88-91`): full은 VIX·LSR·ETF 확장, core는 결측 내성 높은 4피처. 좋은 이중화 설계.
- 서브지수 4종(sentiment/positioning/flow/vol, `subindices.py:36-53`)도 그룹별 PCA — 데이터 주도.

**판정**: 이 계층의 가중치는 문제 없음. 오히려 모범적(임의 가중 회피).

### 1.2 🔴 결함 — 뉴스 감성 집계는 단순 비가중 평균
가장 실질적인 가중치 결함. `_compute_sentiment_aggregate()`(`public_site.py:555-583`):

```python
scores = [s for item in items if (s := item.get("sentimentScore")) is not None]
mean = sum(scores) / n            # 단순 산술평균
```

문제점:
- **FinBERT confidence 폐기**: `finbert_sentiment.py:155`가 기사별 `confidence`(=max(p_pos,p_neg,p_neu))를
  산출하지만 집계에서 **전혀 사용 안 함**. 확신도 0.35짜리 애매한 기사와 0.95짜리 명확한 기사가 동일 가중.
- **소스 신뢰도 무시**: 어느 매체/발행처든 1표. 저품질·스팸성 기사가 고신호 기사와 동등.
- **최신성 무시**: 하루 내 발행 시각 무관.
- **기사 수 정규화 없음**: `news_sentiment_mean`이 그날 우연히 수집된 기사 구성에 좌우됨.

이 `news_sentiment_mean`이 lag1으로 **PCA 핵심 피처**(`hybrid_index.py:37`, `subindices.py:39`)와
**sentiment 서브지수의 주요 입력**으로 들어가므로, 상류 잡음이 하류 지수로 전파됨.

> **개선안**: confidence 가중 평균(`Σ score·conf / Σ conf`) 최소 적용. 표본 대비 A/B로 예측력 비교.
> 부가로 소스별 신뢰도 테이블(선택)·기사 dedup 확인 필요(아래 3.3).

### 1.3 ⚠️ 미세 — median 계산 부정확
`public_site.py:573`: `median = sorted_scores[n // 2]` — **짝수 n에서 진짜 중앙값 아님**(두 중앙값 평균이 아니라
상위 중앙 원소를 취함). 감성 지표라 영향은 작지만 표시용 `median` 필드가 미세 편향. `statistics.median()` 권장.

### 1.4 ✅ 아레나 사이징 — 문서화된 리스크 기반 가중
포지션 가중치 `min(변동성타깃, 리스크타깃)`(CLAUDE.md `execution_rules.combined_position_weight()`)은
거래당 자본위험 1.5%로 균질화하는 원칙 기반 설계. 문제 없음(별도 감사 대상 아님).

---

## 2. 신뢰성(Reliability) 분석

### 2.1 ✅ 모든 소스에 방어 패턴 일관 적용
정독 결과 전 소스가 **retry + fallback + WARNING 로깅 + `fallback_used` attr** 패턴을 준수:

| 소스 | 1차 | 폴백 | 근거 |
|---|---|---|---|
| BTC 가격 | Binance API | `data-api.binance.vision` 미러 | `binance.py:81-97` |
| VIX | FRED VIXCLS | (없음, None 반환) | `vix.py:58-89` |
| ETF flow | Supabase gold_history | 공식 최신 스냅샷 | `etf_flows.py:114,223` |
| Stablecoin | Supabase 캐시 | DefiLlama + fallback ID | `defillama_stablecoins.py:50-58` |
| USD/KRW | KIS API | yfinance | `usdkrw_prices.py` |
| breadth | 로컬 직접 | Lambda | `binance_breadth.py:47-55` |
| 뉴스감성 재수집 | R2 GET | None(graceful) | `r2_sentiment.py:100-110` |

`fallback_used` attr로 다운스트림이 폴백 여부 추적 가능 — 좋은 관측성.

### 2.2 ✅ 누수 방지(lag1) 일관 적용
regime 피처 전부 `_lag1` 시리즈 사용(`risk_overlay.py:185-218`) — ETF/LSR/taker/breadth/stablecoin 모두
전일값 롤링 z. D+1 가용 원칙 준수. 백테스트-라이브 정합에 중요.

### 2.3 ✅ 품질 게이트·이상치 정책 존재
- coverage 게이트: `STRUCTURED_SOURCE_MIN_COVERAGE_RATIO = 0.60`(`quality.py:3`) → degraded 마킹.
- 이상치: IQR×3.0(`outlier_policy.py:42`), `data_error`/`regime_stress`/`iqr_single` 분류(레짐 스트레스는
  보존, 데이터 오류만 마스킹) — 정교한 처리.

### 2.4 ⚠️ 신뢰성 리스크 항목
1. **뉴스→조인 1일 지연**(구조적): A가 어제자 감성을 R2에 쓰고 B가 다음날 흡수(`r2_sentiment.py`).
   누수 방지 목적이라 의도된 것이나, **뉴스 반응이 1일 느림**. 급변 뉴스장에서 신호 지연.
2. **VIX 주말/휴장 stale**: FRED VIXCLS는 미 장중 일별. 주말·공휴일엔 마지막 값 유지 → lag1과 겹쳐 최대
   2~3일 stale 가능. arena는 `MACRO_STALE_HOURS`(48h)로 방어하나 sentiment_join 쪽 명시적 stale 컷은 약함.
3. **coverage 0.60은 관대**: 40% 결측이어도 "ok" 아래(degraded)일 뿐 계산은 진행. 저커버리지 구간의
   지수 신뢰도가 실제로 낮은지 표본 검증 필요.
4. **min-max 스케일 비정상성**: 저장되는 `full_hybrid_index_score`(0~100)는 전체 df in-sample min/max로 스케일
   (`hybrid_index.py:487`). 새 극단값이 들어오면 과거 점수가 재스케일됨(비정상). "오늘 점수"는 OOS 경로
   (`compute_today_score_oos`, `hybrid_index.py:590`)가 train min/max+clip으로 누수 없이 처리하므로 실사용은 안전.
   단 **히스토리 점수 시계열을 그대로 비교하면 오해 소지**(리스케일 아티팩트).

---

## 3. 데이터 유의미성 (수집하는 게 실제로 쓸모 있나)

### 3.1 🔴 exchange_outflow — 미구현 스캐폴딩 방치
`sources/exchange_outflow.py`는 전 제공자가 `NotImplementedError`(`:149,169,190`). `join.py:670-684`에
연결 지점이 **주석 처리된 채** 방치. CLAUDE.md "다음 작업 #1"으로 6주+ 등록돼 있으나 미진전.

**결정 필요**: (a) 제공자 확정 후 구현하거나 (b) 우선순위 아웃 처리하고 스캐폴딩 제거·문서 정리.
현 상태는 "할 일 목록 상단을 계속 점유하는데 진전 없는" dead weight.

### 3.2 ⚠️ SJM 섀도우 — 아직 무의미 (표본 부족)
`risk_overlay.py:129-162`. 2026-07-14부터 관측 시작(CLAUDE.md 기록 07-11과 불일치), **전 관측치 `sjm_bear`
단일**(2026-07-24 확인, 별도 진단). 한 번도 전환 안 해 승격 판단 근거 자체가 아직 없음. 관찰 계속(≥1회 전환 필요).

### 3.3 ⚠️ 뉴스 기사 dedup 미확인
`pipeline.py`에서 명시적 dedup(`drop_duplicates`/URL·title 유니크) 코드가 안 보임. 같은 사건 다수 매체 중복
보도가 감성 평균을 편향시킬 수 있음(1.2와 결합 시 악화). **확인·보강 후보**.

### 3.4 ✅ 나머지 매크로/시장 피처는 실사용
regimeRaw 16피처가 arena 6알고 게이트로 실제 소비됨(CLAUDE.md 게이트 표와 일치). breadth·stablecoin·LSR·taker·
MA200·drawdown 전부 특정 알고 veto에 연결. gate_block_rates 재실행(2026-07-24) 결과 대부분 "유효 필터"로 확인.

---

## 4. 아레나 기술지표 수집 — 별도 점검

- **결정론적·순수 계산**(`indicators.py`, 외부 라이브러리 없음): RSI/MACD/BB/EMA/ADX/Donchian/ATR/realized_vol.
  가중치 이슈 없음(공식 기반).
- **미마감봉 제거**(`scheduler.py:81-83` `klines[:-1]`) — look-ahead 방지 정확.
- **4h 사이클**(`scheduler.py:1294`)에 지표 계산→저장→알고 실행 순서 일관.
- ⚠️ **청산 스트림 사실상 죽음**(WI-9, CLAUDE.md 기록): `fstream.binance.com`이 EC2(서울)에서 프레임 미전달로
  `arena_liquidation_bars` 0건. 수집 전용이라 트레이딩 무영향이나 "수집한다고 표기됐는데 0건"인 상태. REST 서드파티
  교체 or 리전 재시도 필요(사용자 결정 대기).

---

## 5. 우선순위별 개선 권고

| # | 항목 | 심각도 | 공수 | 근거 |
|---|---|---|---|---|
| 1 | ❌ 뉴스 감성 **confidence 가중 평균** — **A/B 기각(2026-07-24)** | ~~🔴 높음~~ | — | §6 |
| 2 | 뉴스 기사 **dedup** 확인·보강 — **A/B에서 dup 48.9% 실측**, 승격 후보 | ⚠️ 중 | 소 | `pipeline.py` (§3.3, §6) |
| 3 | `exchange_outflow` **결정**(구현 or 제거) | ⚠️ 중 | — | `exchange_outflow.py` (§3.1) |
| 4 | ✅ median 계산 `statistics.median()`로 수정 — **완료(53208c9)** | 🟢 낮음 | 소 | `public_site.py:573` (§1.3) |
| 5 | sentiment_join VIX/저커버리지 **명시적 stale 컷** 검토 | 🟢 낮음 | 소 | `vix.py`, `quality.py` (§2.4) |
| 6 | 하이브리드 점수 **히스토리 리스케일 아티팩트** 문서화(비교 시 주의) | 🟢 낮음 | 소 | `hybrid_index.py:487` (§2.4-4) |

**핵심 메시지**: 구조·방어·누수방지·이상치처리는 이미 잘 돼 있다. §1.2에서 "가장 실질적 결함"으로
지목했던 confidence 가중은 **실측 A/B로 예측력 개선이 없음이 확인돼 기각**(§6). 뉴스 단순평균 자체는
IC +0.17로 유효. 남은 실질 레버는 **dedup**(dup 48.9% 실측)과 exchange_outflow 결정 정도.

---

## 6. 검증: 뉴스 감성 confidence 가중 A/B (2026-07-24, ❌ 기각)

§1.2 가설(confidence 가중이 예측력↑) 실측 검증. `scripts/analysis/news_confidence_weight_ab.py`.

**방법**: 과거 기사별 confidence가 어디에도 보존돼 있지 않음(parquet=집계만, raw_backup=점수화 이전 None)을
확인 → 아카이브 raw 텍스트(55일, 2026-04-18~06-14)에 **FinBERT 재실행**으로 (score, confidence) 재구성 →
URL dedup → 날짜별 단순평균/confidence가중 산출 → parquet `btc_fwd_ret_1d/3d`와 병합(누수 없음) →
Spearman IC 비교 + 부트스트랩 5000회 CI.

**결과** (n=52일):

| horizon | IC 단순평균 | IC confidence | 차이(conf−단순) | 95% CI | 판정 |
|---|---|---|---|---|---|
| fwd_1d | +0.1702 | +0.1700 | **−0.0002** | [−0.042, +0.044] | 차이 없음 |
| fwd_3d | +0.0536 | +0.0616 | +0.0080 | [−0.038, +0.061] | CI가 0 포함 |

- 두 집계 평균 절대차 0.038(max 0.14)로 미미. CI가 0을 편안히 포함 → **개선 미확인**.
- ❌ **채택 안 함** — 프로젝트 검증 관례(무효과·미유의 변경 기각)에 따라 배포하지 않음. 배선 미변경(production `_compute_sentiment_aggregate`는 단순평균 유지).

**부수 발견**:
1. 뉴스 **단순평균 IC fwd_1d = +0.17** — 일간 감성 피처로는 유의미한 예측력. 단순평균 유지 정당.
2. **URL dedup rate 48.9%** 실측(699→357건). production `pipeline.py`의 dedup 여부 미확인 —
   confidence보다 **dedup이 더 유망한 레버**일 수 있음(별도 검증 후보, §5 #2).
3. ⚠️ 소표본(n=52, 55일 아카이브 한정). 더 긴 창은 R2 curated 브리프(per-article 점수 보존) 접근 필요 —
   로컬 R2 자격증명 미설정이라 현재 불가.

**확신도**: CONFIRMED(재구성 A/B 실행). 단 결론은 "이 창에서 개선 없음"이며, 소표본이라
"영구히 무효"는 아님 — 다만 재시도는 더 큰 표본 확보 시에만 의미.

---

## 부록: 확신도 표기

- **CONFIRMED**(코드 정독으로 확정): §1.1, §1.2, §1.3, §2.1, §2.2, §2.3, §3.1, §4
- **CONFIRMED**(실측 A/B): §6(confidence 가중 무효과, dedup 48.9%)
- **PLAUSIBLE**(코드 근거 있으나 실측/표본 검증 권장): §2.4(stale 빈도), §3.3(production dedup 여부)
