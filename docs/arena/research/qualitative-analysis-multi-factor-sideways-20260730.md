# 정성 분석 — multi_factor 횡보 허용 재검증 (2026-07-30)

## 배경

파라미터 튜닝 레버가 P1~P8로 소진 확정된 상태([priority-analysis-20260725](priority-analysis-20260725.md),
[dormant-data-audit-20260726](dormant-data-audit-20260726.md))에서, `/arena-status` 세션 중
"quant near-miss 통계가 못 잡는 패턴이 있는가"를 확인하기 위해 라이브 청산 거래 39건의
`signal_reason`/`macro_snapshot` 원문을 직접 읽는 정성 분석을 수행했다.

## 발견

### 1. multi_factor — 손실이 횡보(sideways) 진입에 집중 (채택)

`arena_regime_state`별로 쪼개면:

| 진입 레짐 | n | 승률 |
|---|---|---|
| sideways | 7 | 14% (6패1승) |
| bull_trend | 2 | 50% |
| unknown | 1 | 100% |

WI-1(v28, 2026-07-09)이 "레짐 필수화 + 횡보 허용"으로 설계됐는데(당시 11개월 데이터로
variant C 채택), 라이브 손실의 6/7이 정확히 그 "횡보 허용" 진입에서 나왔다.

### 2. fng_contrarian / vix_rsi — "얕은" 신호가 "깊은" 신호보다 승률↑ (기각)

- fng_contrarian: 손실 7건 평균 진입 FNG≈20.7, 승리 5건 평균 FNG≈26.4
- vix_rsi: 손실 5건 RSI 36.7~47.0, 승리 2건 RSI 48.95/49.5

두 독립 역발산 알고에서 같은 방향 패턴이라 교차검증되는 듯 보였으나, 아래 백테스트에서
기각됨(소표본 착시로 판정).

## 검증 방법

`scripts/analysis/qual_hypothesis_tuning.py` — `wi_tuning.py`와 동일 패턴(20개월 macro
백필, `data/sentiment_join/master_20260710.parquet`, 3766봉, 2024-11-09~2026-07-30).
새 실험용 플래그 `MULTI_FACTOR_ALLOW_SIDEWAYS`(기존), `FNG_CONTRARIAN_MIN_FEAR`/
`VIX_RSI_MIN_RSI`(신규, `parameters.py`)를 그리드 오버라이드.

## 결과

### H1: multi_factor 강세 전용 (`MULTI_FACTOR_ALLOW_SIDEWAYS=False`)

| variant | n | win% | sum_w_ret |
|---|---|---|---|
| A baseline(횡보허용, 구v31) | 146 | 51% | -10.02% |
| B 강세전용 | 51 | 45% | **-0.57%** (Δ+9.45) |

전/후반 분할 검증(2025-09-19 기준 분할, 각 절반 독립 재실행):

| 구간 | baseline sum_w | 강세전용 sum_w | Δ |
|---|---|---|---|
| 전반부 (2024-11~2025-09) | -4.29% | -1.50% | +2.79 |
| 후반부 (2025-09~2026-07) | -5.67% | +0.93% | +6.60 |

양쪽 절반 모두 개선 — 한쪽에 몰린 개선이 아님(omnibus stop A/B가 기각된 이유였던
"전반부에만 몰림" 패턴과 다름). 타 알고 회귀 없음(독립 자본 구조).

⚠️ DSR=0.181로 낮음 — 여전히 PF<1(근처 손익분기)이라 "엣지 발견"이 아니라 "손실 축소"로
해석해야 함(P7 macd RSI 완화와 동일 프레임). 표본이 신뢰구간을 만족하는 수준은 아니라
후속 라이브 트랙레코드로 재확인 필요.

**✅ 채택 (v32)**: `MULTI_FACTOR_ALLOW_SIDEWAYS = True → False`.

### H2a: fng_contrarian 하한밴드 (`FNG_CONTRARIAN_MIN_FEAR`)

| variant | n | sum_w_ret | Δ |
|---|---|---|---|
| baseline | 52 | +2.50% | - |
| min15 | 43 | +0.74% | -1.76 |
| min20 | 34 | -0.70% | -3.20 |
| min22 | 27 | +0.39% | -2.11 |

전부 악화 — 깊은 공포 진입이 실제로는 순기여 중이었음. **❌ 기각**(재시도 금지).

### H2b: vix_rsi 하한밴드 (`VIX_RSI_MIN_RSI`)

| variant | n | sum_w_ret | Δ |
|---|---|---|---|
| baseline | 35 | +5.70% | - |
| min35 | 35 | +5.70% | 0 |
| min40 | 33 | +5.87% | +0.17(노이즈) |
| min45 | 27 | +2.75% | -2.95 |

무효과 확정. **❌ 기각**(재시도 금지).

## 결론 및 배포

- v31→**v32**: `MULTI_FACTOR_ALLOW_SIDEWAYS=False` 적용, 테스트 1건 추가
  (`test_multi_factor_sideways_excluded_by_default`), 151개 arena 테스트 통과.
- `FNG_CONTRARIAN_MIN_FEAR`/`VIX_RSI_MIN_RSI` 인프라는 기본 `None`(off)으로 보존
  (재현 가능하게, 다른 기각된 WI 플래그와 동일 컨벤션).
- 재현: `.venv/bin/python3 scripts/analysis/qual_hypothesis_tuning.py --parquet data/sentiment_join/master_20260710.parquet`
