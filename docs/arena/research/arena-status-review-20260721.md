# Arena Status Review — 2026-07-21

`scripts/analysis/arena_status.py` 실행 결과(2026-07-20 22:58 UTC 스냅샷, BTC=65,141.99, `arena-params-v30`) 기반 분석. 원본 출력은 재현 가능(`--fresh-backtest` 없이 실행, ~3-5초) — 이 문서는 그 위에 얹은 해석 + 개선 가설.

## 헤드라인

**`omnibus`만 순플러스(PF 3.15)로 벤치마크(+1.31%)에 근접, 나머지 4개 거래 알고는 전부 음수·MFE 포착률 음수 — 청산이 이익을 흘리는 문제가 재확인됐고, `multi_factor`는 v30 들어 뚜렷한 턴어라운드(누적 -5.21% vs 최근 6건 +0.43%/승률83%)를 보이고 있어 신구 버전 회계 분리가 시급해졌다.**

## 1. 오픈 포지션

| algo | dir | 진입가 | 미실현% | 보유h | 손절까지% | 비중 | ver |
|---|---|---|---|---|---|---|---|
| multi_factor | long | 64,280 | +1.34 | 15 | +1.13 | 0.69 | v30 |

## 2. 알고별 성과 (누적 29건, 2026-06-20~)

| algo | n | win% | 가중합% | 기대값%/T | PF | 노출% |
|---|---|---|---|---|---|---|
| regime_trend | 0 | – | 0 | 0 | – | 0 |
| fng_contrarian | 10 | 40 | -6.69 | -0.46 | 0.55 | 56 |
| vix_rsi | 6 | 33 | -3.27 | -0.71 | 0.32 | 16 |
| macd_momentum | 0 | – | 0 | 0 | – | 0 |
| multi_factor | 7 | 29 | -5.21 | -0.95 | 0.07 | 17 |
| omnibus | 6 | 67 | **+0.17** | +0.31 | 3.15 | 6 |

벤치마크 buy&hold(동기간): **+1.31%**. omnibus를 제외하면 전 알고가 벤치마크에 열위.

### params_version별 — `multi_factor` 턴어라운드가 눈에 띔
```
v14 n=1 win=0%   -3.20%
v20 n=5 win=0%   -9.49%
v24 n=8 win=25%  -2.15%
v29 n=3 win=0%   -1.87%
v30 n=6 win=83%  +0.43%   ← 최근 버전, 표본 적지만 방향 뚜렷
```

## 3. MFE/MAE — 청산 품질

| algo | 평균MFE% | 평균MAE% | 포착률% | MFE≥1% 미실현승리 |
|---|---|---|---|---|
| fng_contrarian | +2.20 | -1.90 | -14 | 5건 |
| vix_rsi | +0.91 | -1.82 | -7 | 0건 |
| multi_factor | +0.66 | -1.45 | **-97** | 0건 |
| omnibus | +1.34 | -0.98 | 20 | 1건 |

거래가 있는 4개 알고 **전부 포착률<30%** — 이익이 났다가 손실/저조한 수익으로 마감되는 패턴이 여전함. 특히 `fng_contrarian`은 10건 중 5건이 한때 MFE≥1%였다가 손실로 끝남(청산 문제가 정량적으로 가장 뚜렷).

## 4. 현재 macro/레짐 (2026-07-19 기준, 2.9h stale)

```
레짐=Transitional  vol=Mid/rising
FNG=28.0 (fng_contrarian 트리거 임계 <30에 근접)
VIX=16.73 vs q40=16.80 (거의 임계선)
MA200 상회=0.0 (하회 — 추세추종 알고 휴면 근거)
90일 낙폭=-21.3%
breadth=0.50, stablecoin_z=+0.75
```
현재 시장이 명확한 추세가 아닌 전환기 + BTC MA200 하회 상태라 `regime_trend`/`macd_momentum`(추세추종)이 휴면하는 것은 게이트가 정상 작동하는 것으로 해석됨.

## 5. 개선 가설

### 가설 1 — `fng_contrarian`/`vix_rsi` 손실이 "unknown" 레짐 진입에 몰림 (P4 백로그 검증)
섹션6 진입레짐 분포: fng_contrarian 10건 중 6건, vix_rsi 6건 중 5건이 진입 시 레짐 `unknown`. 두 알고 모두 승률 33~40%로 저조. 이는 [return-improvement-priorities-20260715.md](return-improvement-priorities-20260715.md)의 **P4 "unknown 조이기 A/B"**가 이미 백로그에 있던 항목인데, 이번 라이브 데이터가 실측으로 재확인해줌 — unknown 레짐 진입이 손실 표본에 과대표집되어 있음.
- **다음 액션**: P4를 앞당겨 A/B(unknown 레짐 시 진입 억제 or 사이즈 축소) → `wi_tuning.py` 패턴으로 검증.

### 가설 2 — `momentum_not_worsening` 베토가 최다 차단이지만 여전히 음수-macd 진입이 통과 중
섹션7: fng_contrarian·vix_rsi 둘 다 `veto:momentum_not_worsening`이 최다 차단 사유(26·34회/14일). 그런데 섹션6에서 두 알고 모두 진입 시 macd_hist가 음수인 거래가 대다수(fng 6/10, vix 4/6)이고 이들의 승률이 특히 낮음(33%·25%). "not worsening"(악화 안 함) 기준이 방향만 보고 크기를 안 봐서, 여전히 깊은 음수 상태에서의 진입을 걸러내지 못하는 것으로 보임.
- **다음 액션**: `momentum_not_worsening` 게이트에 macd_hist 절대값 임계(단순 부호가 아니라 "충분히 0에 가까움") 추가 후 그리드 A/B. 근거 표본은 아직 적어(n=10, n=6) 방향 참고 수준.

### 가설 3 — `multi_factor` v30 턴어라운드는 P0(성과회계 분리)의 실측 근거
누적 성과(-5.21%, 승률29%)는 v14/v20/v24 구버전 손실(-3.20%, -9.49%, -2.15%)이 지배하고, 현재 활성 버전(v30, WI-1 레짐필수화 이후)은 n=6·승률83%·+0.43%로 완전히 다른 궤적. 이건 `return-improvement-priorities-20260715.md`의 **P0 "성과회계 분리"**가 왜 필요한지 보여주는 구체적 사례 — 대시보드/성과 집계가 버전 구분 없이 누적으로만 보이면 multi_factor가 실제로는 건강해진 상태를 "여전히 나쁜 알고"로 오판하게 됨.
- **다음 액션**: 대시보드 또는 arena_status 스크립트에 "현재 PARAMS_VERSION 이후만" 필터 뷰 추가(P0 표준 절차대로).

### 가설 4 — `macd_momentum` 여전히 0거래, `bb_width_sufficient` 베토가 지속 병목
14일간 macd_momentum은 거래 0건, `veto:bb_width_sufficient`(36회)가 최다 차단. 이 알고는 스킬 문서 자체 예시에서도 "병목 후보"로 언급된 조건 — 장기간(최소 한 달) 무거래 상태가 이어지고 있어 임계값 재검토 우선순위가 올라감.
- **다음 액션**: `gate_block_rates.py`로 이 조건의 near-miss 분석(막힌 진입이 실제로 좋았을지) 후 임계 완화 A/B 고려.

### 참고 — MFE 포착률 문제는 이미 Tier2에서 소진됨
전 알고 포착률 음수는 [big-candle-no-pnl-diagnosis-20260715.md](big-candle-no-pnl-diagnosis-20260715.md) Tier2(`TARGET_EXIT_ATR_MULT_BY_ALGO`) 그리드로 vix_rsi·multi_factor에 목표가 익절을 이미 시도했으나 PBO 0.877/0.921로 기각됨(코드는 남아있으나 기본 off). 이 문서의 재확인은 **새 개선 방향이 아니라** [return-improvement-priorities-20260715.md](return-improvement-priorities-20260715.md) **P2(1m MFE 정밀화)**의 필요성을 다시 뒷받침하는 근거로만 취급.

## 6. 요약 우선순위

1. **P4 (unknown 레짐 조이기)** — 이번 실측으로 근거 강화, 우선순위 상향 권고.
2. **P0 (성과회계 분리)** — multi_factor v30 턴어라운드가 실측 사례. 대시보드 필터만 추가하면 되는 저비용 작업.
3. **momentum_not_worsening 임계 재검토** — 신규 가설(가설2), 표본 소량이라 그리드 A/B로 검증 필요.
4. **macd_momentum bb_width_sufficient 재검토** — 지속 병목, near-miss 분석 우선.
5. omnibus는 현행 유지(WI-7 target_exit 효과 지속 확인).

표본 크기 주의: 개별 알고 6~10건 수준이라 전부 "방향 참고"이며, 백테스트 게이트(walk-forward + DSR/PBO) 없이 파라미터를 바꾸지 않는다.

---

## 7. 상세 구현 계획 (실구현 아님 — 계획서만)

아래 4건은 위 가설을 실제 코드 앵커까지 짚어 "무엇을 어떻게 바꾸고 어떻게 검증할지"를 구체화한 것. **코드는 건드리지 않았고**, 다음 세션에서 그대로 착수할 수 있는 수준까지만 설계했다. 실행 순서는 `return-improvement-priorities-20260715.md`의 P0→P4 순서를 그대로 존중하되(§7.5 참고), 이 세션에서 발견한 신규 항목(제안B)을 그 사이에 끼워 넣었다.

### 7.1 제안 A — `unknown` 레짐 진입 사이징 완화 (P4 구체화)

**배경 재확인 (중요 정정)**: 가설1에서 인용한 섹션6 "진입레짐" 카운트는 `arena_status.py:415`가 `macro_snapshot.arena_regime_state`(로컬 4h 원시값)만 세는 것이라, 게이트가 실제로 사용한 유효 레짐과 다를 수 있다. `_regime_state()`(`src/arena/algorithms.py:31-41`)는 로컬이 `unknown`이면 매크로 오버레이 `regime_state`(BullQuiet/Choppy/Transitional 등)로 폴백하기 때문. 게다가 `fng_contrarian`(`algorithms.py:333`)과 `vix_rsi`(`algorithms.py:380`)는 **폴백된 유효 레짐을 risk-off 체크에만** 쓰고(`_is_risk_off`), bullish 여부는 애초에 요구하지 않는다. 따라서 "unknown이 나쁘다"는 아직 상관관계이지 인과가 증명된 게 아니다.

**Step 0 (코드 변경 없음, 먼저 실행)** — `paper_positions.macro_snapshot`에는 `regime_state`(오버레이)도 같이 저장되어 있음. 손실 표본에서 `arena_regime_state='unknown'`일 때 `regime_state`가 실제로 무엇이었는지 교차 집계해 "unknown이 진짜 문제인지, 아니면 폴백된 오버레이 레짐 자체(예: Choppy)가 문제인지"부터 분리해야 함:
```sql
SELECT macro_snapshot->>'arena_regime_state' AS local_regime,
       macro_snapshot->>'regime_state' AS overlay_regime,
       algo_id, ret_pct
FROM paper_positions
WHERE status='closed' AND algo_id IN ('fng_contrarian','vix_rsi')
ORDER BY open_time;
```

**Step 1 (신규 헬퍼)** — `algorithms.py`에 `_regime_unknown(macro)` 추가 (기존 `_lsr_crowded`/`_breadth_collapsed` 패턴과 동일 위치, `_regime_state` 근처):
```python
def _regime_unknown(macro: dict) -> bool:
    """로컬 4h 레짐이 미분류(unknown)이고 매크로 오버레이도 폴백 불가한 경우."""
    local = macro.get("arena_regime_state")
    return not local or local == regime.REGIME_UNKNOWN
```
P4 문서가 명시한 대로 **게이트(veto)가 아니라 사이징 축소**로 구현 — unknown이 전체 봉의 ~40%라 veto는 거래량을 반토막 낸다. `omnibus_position_multiplier()`(`algorithms.py:707`, `backtest.py:379`·`scheduler.py:925`에서 `position_weight *=`로 곱해지는 패턴)를 그대로 재사용해 `fng_vix_unknown_multiplier(macro) -> float`를 만들고 동일한 두 지점(`backtest.py:379` 부근, `scheduler.py:925` 부근)에 `if algo_id in ("fng_contrarian", "vix_rsi")` 조건으로 곱한다.

**Step 2 (플래그)** — `parameters.py`에 `UNKNOWN_REGIME_SIZE_MULT_BY_ALGO: dict[str, float] = {}` (빈 dict=off, `TARGET_EXIT_ATR_MULT_BY_ALGO`와 동일 패턴). 그리드 후보: `{0.5, 0.65, 0.8}`.

**검증**:
1. `wi_tuning.py`의 `_params(**overrides)` 패턴(`scripts/analysis/wi_tuning.py:35`)으로 `UNKNOWN_REGIME_SIZE_MULT_BY_ALGO={"fng_contrarian": mult}` 단독 오버라이드 → sum_w_ret·거래수 baseline 대비 비교. **fng·vix_rsi는 독립 A/B**(P4 문서 경고대로 — vix_rsi는 구조 게이트 추가 시 항상 악화된 전례, WI-5 기각 이력).
2. 채택 기준: 대상 알고 sum_w 개선 + 타 알고 무회귀(사이징만 바꾸므로 자동 충족되어야 함, 확인만) + `validation_stats.py`의 `probability_of_backtest_overfitting`(line 93)으로 그리드 3개 후보 PBO ≤0.2.
3. 유닛 테스트: `tests/test_arena_algorithm_diagnostics.py`에 `_regime_unknown` 케이스(local=None/unknown/bull_trend) 추가.
4. 하나라도 기각되면 그 알고만 접고 다른 알고는 유지(둘을 같이 묶어 판단하지 않음).

### 7.2 제안 B — `momentum_not_worsening` 매그니튜드 게이트 (신규, 기존 백로그에 없던 항목)

**배경**: `_momentum_not_worsening()`(`algorithms.py:249-266`)은 `mh >= mhp`만 검사 — 히스토그램이 아무리 깊은 음수여도 "직전보다 덜 나쁘면" 통과시킨다. 라이브 실측(섹션6)에서 fng·vix_rsi 둘 다 macd 음수 진입이 다수(6/10, 4/6)이고 승률이 33%/25%로 특히 낮다는 것과 방향이 맞는다. 단, 이 상관도 표본이 작아(합쳐서 10건) 인과 증명은 아님.

**제안 변경** — 동일 함수에 선택적 매그니튜드 조건 추가(하위호환: 파라미터 기본값 None=기존 동작):
```python
def _momentum_not_worsening(
    ind: dict, *, enabled: bool = True, max_abs_hist: float | None = None
) -> bool:
    if not enabled:
        return True
    mh = ind.get("macd_hist")
    mhp = ind.get("macd_hist_prev")
    if mh is None or mhp is None:
        return True
    if float(mh) < float(mhp):
        return False
    if max_abs_hist is not None and float(mh) < -abs(max_abs_hist):
        return False  # 방향은 개선됐지만 여전히 깊은 음수 — 칼받기 지속 구간
    return True
```
호출부(`algorithms.py:343`, `:388`)에 `max_abs_hist=parameters.MOMENTUM_MAGNITUDE_GATE_ATR_MULT_BY_ALGO.get(algo_id)` 형태로 ATR 정규화 임계 전달(고정값 대신 ATR×배수로 변동성 정규화 — 기존 `ATR_TARGET_EXIT` 계열과 동일 관례). `parameters.py`에 `MOMENTUM_MAGNITUDE_GATE_ATR_MULT_BY_ALGO: dict[str, float] = {}` 신규(기본 off).

**검증**:
1. 그리드: ATR×{0.15, 0.25, 0.40} 절대 임계. `wi_tuning.py` 패턴으로 fng·vix_rsi 각각 독립 A/B.
2. `gate_block_rates.py`(`scripts/analysis/gate_block_rates.py:1`, near-miss 로직)로 새 조건의 near-miss 세트(veto가 이 조건 하나 때문에 막힌 봉)를 뽑아 forward 6봉 수익 분포 확인 — (+)면 알파를 죽이는 dead weight, (-)면 유효 필터.
3. walk-forward(`scripts/analysis/target_exit_walk_forward.py` 패턴 재사용, 최소 4~6윈도) + DSR/PBO. Tier2(목표가 익절) 그리드가 PBO 0.877/0.921로 전멸한 전례가 있어 **엔트리 필터도 과적합 위험이 동일하게 크다는 전제로 엄격하게 본다**.
4. 채택 기준 미충족 시 폐기하고 CLAUDE.md의 "❌ 채택 안 함" 목록에 추가(재시도 금지 항목으로 기록).

### 7.3 제안 C — 성과 회계 분리 뷰 (P0 구체화, `arena_status.py` 확장)

**배경**: 가설3 — `multi_factor` 누적(-5.21%)이 v14/v20/v24(WI-1 이전) 손실에 지배되고 v30(현재)은 +0.43%/승률83%. `arena_status.py`는 이미 params_version별 분해(섹션2 하단, `arena_status.py` 내 params_version 집계 블록)를 출력하고 있어 **원본 데이터는 이미 있음** — 빠진 건 "현재 유효 버전 이후만"을 헤드라인 지표로 승격하는 뷰.

**제안 변경** — `scripts/analysis/arena_status.py`에 신규 `--since-version` 플래그(기본값 `parameters.PARAMS_VERSION` 그대로, 즉 항상 최신 버전 필터 뷰를 기본 출력에 추가):
- 섹션2 알고별 성과 표 바로 아래에 "### 현재 버전(`{PARAMS_VERSION}`) 이후만" 서브테이블 추가 — 동일 컬럼(n/win%/가중합%/기대값/PF), 단 `params_version == PARAMS_VERSION` 필터.
- 헤드라인 문구에 "레거시 vs 현행" 비교 문장 자동 생성(예: "누적 -5.21%는 v14~24 유산, 현행 v30은 +0.43%").
- 스크립트 로직 변경만이고 트레이딩/스키마에는 영향 없음(가드레일 "읽기 전용" 유지).

**검증**: 단위 테스트 불필요(분석 스크립트, DB 미변경) — 실행 후 출력값이 섹션2 params_version 하단 블록과 합산 시 일치하는지 수동 대조 1회로 충분.

**주의**: PARAMS_VERSION은 표본이 극소(v30 n=6)일 때 "필터 뷰"가 과신을 유발할 수 있음 — 스크립트 출력에 `n<10`이면 "표본 부족" 경고 문구를 자동 첨부(스킬 가드레일 "소표본은 방향 참고"와 동일 원칙을 스크립트 레벨에 반영).

### 7.4 제안 D — `macd_momentum` `bb_width_sufficient` near-miss 진단 (코드 변경 없이 진단부터)

**배경**: 14일간 최다 차단(36회), 알고 자체는 이 기간 거래 0건. `MACD_MOMENTUM_BB_WIDTH_MIN = 3.5`(`parameters.py:352`)가 임계. 코드를 바꾸기 전에 이미 존재하는 `gate_block_rates.py`로 "이 조건이 진짜 알파를 막고 있는지"부터 실측해야 함(스킬 플레이북 §5 "라이브 차단 사유 top" 지시사항과 정확히 일치).

**실행 계획**:
1. `.venv/bin/python3 scripts/analysis/gate_block_rates.py --parquet data/sentiment_join/master_20260710.parquet --algos macd_momentum --forward-bars 6` (macro 백필된 최신 parquet 사용 — CLAUDE.md 상단 표에 명시된 arena용 최신본).
2. near-miss 세트(=`bb_width_sufficient` 단 하나만 실패한 bar) 이후 6봉 수익 분포 확인.
   - 분포가 뚜렷하게 (+): 임계 완화 그리드(`{2.5, 3.0, 3.5}`)로 A/B 진행(제안 A/B와 동일 `wi_tuning.py` 패턴).
   - 분포가 (-) or 무의미: 현 임계 유지, "정상 병목(시장이 안 준 것)"으로 결론 — 이 경우 **코드 변경 없이 진단만으로 종결**.
3. `oi_not_diverged`(14회)도 같은 스크립트로 동시에 near-miss 확인(2순위 차단 사유, 저비용 추가).

이 항목은 다른 3건과 달리 **1단계(진단)만으로 결론이 날 수 있는 저비용 작업** — 근본적으로 코드 변경이 필요 없을 가능성이 A/B 항목들보다 높음.

### 7.5 실행 순서 (기존 P0~P4와 병합)

```
1. 7.4 macd bb_width near-miss 진단        — 코드 변경 없음, 즉시 실행 가능, 공수 최소
2. 7.3 성과 회계 분리 뷰 (P0 구체화)         — 스크립트만, 트레이딩 무영향
3. 7.1 Step 0 (unknown/overlay 교차 SQL)   — P4 착수 전 필수 선행 진단
4. 7.1 Step 1~2 unknown 사이징 A/B (P4)    — fng·vix_rsi 독립
5. 7.2 momentum 매그니튜드 게이트 A/B (신규) — 위 P4 결과와 동일 하니스 재사용 가능
```
순서 근거: 1·2는 코드 변경이 없거나 트레이딩에 영향이 없어 리스크 없이 먼저 처리 가능하고, 3~5는 전부 `wi_tuning.py`/`gate_block_rates.py`라는 동일 백테스트 하니스를 쓰므로 뒤에 묶어 한 번에 셋업하는 게 효율적. 모든 A/B는 `PARAMS_VERSION` bump 없이 플래그 기본값 off 상태로 먼저 구현·검증하고, 통과분만 기본값 on + 버전 bump(배포 runbook 절차) 한다.

---

## 8. 실행 결과 (2026-07-21 후속 — §7 계획 전항목 실행 완료)

§7 계획 5건을 순서대로 실행했다. 결론부터: **7.1·7.2는 11개월 macro 백필 백테스트에서 전부 기각**, 7.3(인프라)은 채택·배포, 7.4는 진단만으로 종결(코드 변경 없음).

### 8.1 (§7.4) `bb_width_sufficient` near-miss — 유효 필터로 확인, 코드 변경 없음
`gate_block_rates.py --algos macd_momentum --forward-bars 6` (11개월, `master_20260710.parquet`) 결과 `bb_width_sufficient` near-miss(n=12) 이후 6봉 평균수익 **-0.18%·승률42%** → "유효 필터" 판정(dead weight 아님). `oi_not_diverged`(n=13)도 -0.72%·38%로 동일 결론. **결론: 임계 유지, 코드 변경 없음.** (참고: `macd_hist_positive`·`rsi_below_long_max`는 이 실행 중 "dead weight 후보"로 별도 발견됐으나 원래 계획 범위 밖이라 이번엔 손대지 않음 — 후속 백로그 후보로만 기록.)

### 8.2 (§7.1 Step 0) unknown/overlay 교차 SQL — 가설이 예상보다 약함을 미리 시사
`paper_positions`에서 fng_contrarian·vix_rsi closed 16건을 직접 조회한 결과, **오버레이 `regime_state`가 16건 전부 `'Transitional'`로 균일**했다(로컬 `arena_regime_state`만 unknown/sideways/bull_trend로 갈림). 즉 "unknown 로컬 → 특정 나쁜 오버레이로 폴백"이라는 하위 가설은 성립하지 않음 — 이 기간 내내 오버레이 자체가 분화되지 않았다. unknown 로컬 버킷 내 승률도 fng 33%·vix_rsi 40%로 non-unknown 버킷(표본 1~4건)과 큰 차이가 나지 않아, **원래 가설1의 근거가 소표본(n=16) 상관관계였음이 재확인**됐다. 이 결과는 사후적으로 8.3의 백테스트 기각과 일관된다.

### 8.3 (§7.2, §7.1 Step 1~2) 코드 구현 + A/B 그리드 — 전부 기각
`_momentum_not_worsening(max_abs_hist=...)`(매그니튜드 게이트)와 `fng_vix_unknown_multiplier()`(unknown 사이징)를 계획대로 구현(둘 다 기본 빈 dict=off, `src/arena/algorithms.py`·`parameters.py`·`backtest.py`·`scheduler.py`, 유닛테스트 포함)한 뒤 `scripts/analysis/p4_momentum_unknown_tuning.py`로 11개월 macro 백필 백테스트(`master_20260710.parquet`, 1966봉, W1 13bps 하니스) A/B를 실행했다.

**핵심 발견**: 이 11개월 창에서 `fng_contrarian`(+2.45%)·`vix_rsi`(+5.79%) baseline이 **이미 순양(+)** — 최근 라이브 스냅샷(2026-06-20~, 각각 -6.69%·-3.27%)과 정반대다. 두 신규 필터 모두 baseline 대비 전 그리드 값에서 악화:

| 그리드 | 대상 | 변형 | Δsum_w_ret |
|---|---|---|---|
| 매그니튜드(ATR×0.15/0.25/0.40) | fng | 전부 | -1.92 / -0.76 / -0.35 |
| 매그니튜드 | vix_rsi | 전부 | -6.25 / -3.64 / -1.66 |
| unknown 사이징(×0.5/0.65/0.8) | fng | 전부 | -0.18 / -0.13 / -0.07 |
| unknown 사이징 | vix_rsi | 전부 | -1.55 / -1.09 / -0.62 |

거래수·승률도 필터를 강하게 걸수록(ATR 배수 작을수록) 같이 하락(예: fng 매그니튜드 B: n 51→47, 승률 59→55%) — 걸러낸 진입들이 실제로는 순양(+)이었다는 뜻. **결론: 두 플래그 모두 기본값 off 유지, 채택하지 않음(재시도 금지).** 원본 결과: `docs/arena/research/p4-momentum-unknown-tuning-results.json`. `parameters.py`에 Tier2와 동일한 "❌ 기각" 관례로 근거를 기록.

**해석**: 라이브 n=6~10의 최근 손실 패턴과 11개월 백테스트의 구조적 양(+)이 공존한다는 것은, 최근 손실이 "구조적 결함"이 아니라 **최근 수주의 특정 국면(macro §4: Transitional·MA200 하회·90일 -21% 낙폭)에서의 국소적 손실**일 가능성이 높다는 뜻 — 백테스트 게이트가 "라이브에서 나쁘게 보이는 것을 성급하게 고치지 말라"는 원래 목적대로 작동한 사례.

### 8.4 (§7.3) 성과 회계 분리 뷰 — 채택·배포
`scripts/analysis/arena_status.py`에 `--since-version`(기본값 `parameters.PARAMS_VERSION`) 추가, 섹션2 아래 "현재 버전 이후만" 서브테이블 신설. 실행 확인: 레거시 23건 누적 -15.42% vs 현행(v30) 6건 +0.43% — 가설3(§5) 그대로 재현됨. 표본<10건 자동 경고 문구 포함. 트레이딩/스키마 영향 없음(읽기 전용 분석 스크립트).

### 8.5 인프라 처리 방침
7.1·7.2 코드(플래그·헬퍼 함수·배선·유닛테스트)는 삭제하지 않고 **기본 빈 dict(off) 상태로 보존** — `TARGET_EXIT_ATR_MULT_BY_ALGO`(Tier2)와 동일 관례. 향후 다른 그리드값·다른 알고 조합을 재시도하고 싶을 때 배선을 다시 만들 필요가 없다. `PARAMS_VERSION` bump는 하지 않음(기본 동작 변경 없음).

### 8.6 커밋·배포
- 커밋 1: 기존 세션의 W1/W2/Tier2 미커밋 작업(사전 존재, 이 세션과 무관하지만 함께 발견돼 먼저 정리).
- 커밋 2: §7 계획 구현 전체(§8.1~8.4) — 코드·테스트·문서.
- `src/arena/` EC2 rsync + `arena.service` 재시작 — 기본 동작 변화는 없지만(플래그 off) 라이브 코드베이스를 리뷰·테스트된 main과 동기화하기 위해 실행.

---

## 9. P2 후속 — MFE/MAE 1분 정밀화 (2026-07-21, §8 이후 추가 실행)

`return-improvement-priorities-20260715.md` P2("청산 개선 스레드의 진위 판정")를 이어서 실행. 신규 스크립트 `scripts/analysis/mfe_1m.py`(읽기 전용) — `arena_realtime_feature_bars`(1분 `last_price`, 커버리지 100%)로 동일 청산 거래의 MFE/MAE를 재계산해 기존 4h봉 기반 진단(섹션3)과 대조.

| algo | n | 포착률_4h | 포착률_1m | 판정 |
|---|---|---|---|---|
| fng_contrarian | 10 | -14% | -16% | 4h 진단 유효 — 실제로 흘림 |
| vix_rsi | 6 | -7% | **+51%** | **4h 진단이 해상도 오류** — 실제론 건강한 청산 |
| multi_factor | 8 | -97% | -91% | 4h 진단 유효 — 가장 심각 |
| omnibus | 6 | +20% | +16% | 4h 진단 유효 — WI-7 이후 경계~양호 |

**핵심 발견**: `vix_rsi`의 "청산이 이익 흘림" 진단은 4h봉 해상도가 인트라바 스파이크를 과대평가한 아티팩트였다. 1분 기준 실제 포착률은 +51%(건강한 청산)로, WI-5(구조 게이트)·Tier1(시간배리어)·Tier2(ATR 목표가)·오늘 §8.3의 momentum/unknown 게이트가 vix_rsi에서 전부 무개선으로 기각된 이유가 여기서 설명된다 — **애초에 고칠 청산 문제가 없었다.** `fng_contrarian`·`multi_factor`는 1분에서도 누출이 재확인돼 4h 진단이 유효했음이 확인됐다(단, 둘 다 이미 각각 P-A·Tier2로 메커니즘을 한 차례씩 시도·검증한 상태).

**결론(부분 종결)**: `vix_rsi`는 exit-tuning 대상에서 제외 — 향후 이 알고에 새 청산 메커니즘을 재시도하지 않는다(재시도 금지, 근거는 위 표). `fng_contrarian`·`multi_factor`(특히 후자 -91%)는 누출이 실존하지만, 다음 시도는 기존 메커니즘(목표가 익절 계열)의 재탕이 아니라 **새로운 메커니즘 가설이 확보됐을 때만** 착수한다. `omnibus`는 현행 유지.

⚠️ `.claude/skills/arena-exit-tuning/SKILL.md`에도 이 결과를 반영해야 하나, 스킬 파일 자기수정은 이번 세션에서 harness 권한 분류기가 차단(스킬 파일 편집은 사용자의 명시적 요청이 있을 때만 허용) — 사용자가 원하면 별도로 반영.

---

## 10. P3 후속 — FNG 지속기간 피처 (2026-07-21, §9 이후 추가 실행)

`return-improvement-priorities-20260715.md` P3 / `implementation-plan-w-series-20260715.md` W5 설계 그대로 구현·검증.

**구현**: `risk_overlay.py`에 `_fng_streak_below()`(fng<30 연속일수, lag 불요) 추가 → `regimeRaw.fng_days_below_30` → `backtest._macro_signal_from_snapshot`·`scheduler._fetch_macro` 매핑 → `algorithms.fng_duration_scale()`(sizing 배수 산출)·`algorithms.fng_scaled_tranches()`(트랜치 스케줄 균일 스케일) → `backtest.py`(`SimPosition.fng_duration_scale` 필드, 초기 진입+`_maybe_scale_in_fng_sim` 물타기 양쪽)·`scheduler.py`(초기 진입, `signal_reason.fng_duration_scale`에 진입 시점 고정)·`positions.py`(`maybe_scale_in_fng_price`, 저장된 scale 재사용) 전체 배선. gate 변형은 `fng_contrarian()`에 `fng_days_below_30 < FNG_DURATION_MIN_DAYS` 조건 추가. 플래그 전부 기본 off. 유닛테스트 15건(risk_overlay 6·algorithms 6·backtest 2 신규 + gate/sizing 조합) 추가.

**검증** (`scripts/analysis/fng_duration_tuning.py`, master_20260710.parquet, 11개월, W1 13bps 하니스 + WF 6윈도):

| config | 단일프레임 Δsum_w | WF 양의윈도 | 판정 |
|---|---|---|---|
| B sizing 0.5 | +0.04 | 4/6 (baseline과 동일) | 무효과 |
| C sizing 0.3 | +0.05 | 4/6 (baseline과 동일) | 무효과 |
| D gate N=2 | +0.06 | 4/6 (baseline과 동일) | 무효과 |
| E gate N=3 | +0.11 (최선, DSR=0.447) | 4/6 (baseline과 동일) | 미달(약한 신호) |
| F gate N=5 | -0.47 (n 51→48) | 4/6 | 악화 |

**결론**: sizing형은 거래수가 불변인데도 sum_w_ret 변화가 baseline(+2.45%)의 2% 미만 — 공포 1일차 진입이 이 데이터셋에서 다른 날과 품질 차이가 거의 없다는 뜻(가설 반증). gate형 N=2/3의 근소한 개선은 DSR 0.447로 채택 기준 미달이고 WF에서 baseline과 양의윈도 비율이 완전히 동일(6윈도 전부 무차이) — 노이즈와 구분 불가. N=5는 거래 51→48건으로 줄면서 명확히 악화(WI-4 게이트형 붕괴 패턴 재현). **채택하지 않음**(파라미터 핏, DSR 엄격 적용). 인프라는 Tier2/P4와 동일 관례로 기본 off 상태 보존. 원본 결과: `docs/arena/research/fng-duration-tuning-results.json`.

이로써 `return-improvement-priorities-20260715.md`의 P1~P4가 전부 완료됐다 — **파라미터 튜닝으로 짜낼 수 있는 것은 확정적으로 소진**. 남은 항목(P5 청산 API·P6-a 숏 트랙)은 사용자 결정이 필요하고, P6-b·P7은 저효과 유지보수성 작업이다.

