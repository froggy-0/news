# 남은 개선 백로그 — "기다리는 것 외에 할 수 있는 일" (2026-07-10)

> **성격**: v29(P-A 익절)·청산 수집 가동 이후 "이제 관찰만 남았나?"에 대한 답.
> 결론: **아니다.** 데이터 축적을 기다려야 하는 항목(§1)과 별개로, 지금 바로 실행 가능한
> 개선(§2)·인프라/프로세스 개선(§3)이 남아 있다. 선행 문서:
> [return-optimization-research](return-optimization-research-20260709.md)(P1~P8),
> [improvement-plan-v2](improvement-plan-v2-20260710.md)(P-A~P-D, 완료).
>
> **진행 현황 (2026-07-11)**: R1·R2·R4·R7 완료. R3 SJM 섀도우가 다음 최우선.

---

## §1. 대기 항목 (데이터 축적 — 액션 없음, 타임라인만)

| 항목 | 관찰 조건 | 예상 시점 | 확인 방법 |
|---|---|---|---|
| P-A fng 익절 라이브 검증 | `close_reason=target_exit` 표본 n≥5 | 수주 (FNG<30 발생 빈도 의존) | `/arena-status` MFE 포착률·v29 분리 |
| P-B vix_rsi 재평가 | v26+ 진입 표본 n≥10 | ~2-4주 | `/arena-status` params_version 분리 |
| P-C 주간 백테스트 첫 저장 | 다음 월요일 00:10 UTC | 2026-07-13 | `/arena-status` 섹션5 STALE 경고 소멸 |
| P-D 청산 데이터 → 지표 연결 v2 | 🔴 2026-07-14 재평가: 축적이 아니라 **수집 자체가 0건**(EC2 fstream 구조적 네트워크 문제, [진단](priority-improvements-20260714.md) P1-3) — "기다리면 찬다"는 전제가 깨짐. 재개 조건: 네트워크 경로 확인 또는 서드파티 API 교체 | 보류(재조사 필요) | `SELECT count(*) FROM arena_liquidation_bars` |
| WI-1/7(v28) 라이브 검증 | multi_factor·omnibus 신규 표본 | 수주 | params_version 분리 |
| regime_trend/macd 첫 진입 | 강세 레짐 도래 (현재 bullish_regime 73회 차단) | 시장 의존 | 섹션7 차단 사유 변화 · 진단+계획: [regime-macd-diagnosis](regime-macd-diagnosis-20260711.md) (무거래=정상, 게이트 완화 금지, SJM이 구제 경로) |

---

## §2. 지금 실행 가능한 개선 (우선순위순)

### ✅ R1. 백테스트 macro 커버리지 갱신 — 완료 (2026-07-10)
`master_20260710.parquet` 확보 완료. 이후 모든 검증(R2·R4·R7)이 fresh macro로 실행됨.

### ✅ R7. v29 walk-forward 검증 — 완료 (2026-07-11)
`walk_forward_validate.py` 6윈도 실행. P-A atr2.0이 5/6 윈도 우위(fng 평균 +0.36 vs atr1.0 +0.03)
→ stale macro 결론(atr1.0) 번복, atr2.0 채택(arena-params-v30).

### ✅ R2. P3: 변동성 추정기 EWMA — 완료 (2026-07-11, off 확정)
`indicators.realized_vol_sizing()` + `VOL_ESTIMATOR_ROBUST_ENABLED=False` 배선·배포 완료.
A/B 백테스트 Δ+0.00 → max-bounds(0.25~0.7)가 차이를 흡수. 플래그 off 유지, 배선은 남김.

### ✅ R4. fng_optimize 재실행 — 완료 (2026-07-11, 라벨 버그 2026-07-14 수정)
P-A익절(atr2.0) 상태에서 ts×mh 재그리드(master_20260710):
- **ts 72→60h, mh 48→36h 적용·배포** (arena-params-v30): 3단 ts60·mh36 종가자산 1.0269 vs 현행 1.0214.
  ⚠️ 파라미터 값 자체는 커밋 시점에 정상 반영됐으나 `PARAMS_VERSION` 상수 bump가 누락돼
  2026-07-11~07-14 거래가 DB에 v29로 오기록되던 버그가 있었음 — 2026-07-14 수정(v25 때와
  동일 클래스 재발, [진단](priority-improvements-20260714.md) P0-1). "완료" 마킹은 파라미터
  값 기준으로는 정확했지만 배포 확인(버전 라벨)까지는 실제로 안 됐던 상태였다는 교훈.
- **물타기 제거(0.15 단일) 1위(1.0339)** 발견 — P-A익절 활성화 후 추가 트랜치 효용 감소.
  근본 변경이라 별도 walk-forward 검증 후 결정 → 아래 R4b 참조.

### R3. P1: SJM(통계적 점프모델) 레짐 — ⚡ 지금 착수 (30일 시계)
- **문제**: rule 기반 4h 레짐의 `unknown` 빈발·whipsaw. 레짐은 6알고 공유 게이트라
  개선 시 전 알고 수혜. 라이브 진단에서도 손실이 unknown 레짐 진입에 집중.
- **액션**: `jumpmodels` 패키지로 일간 피처(parquet) 오프라인 학습 → regimeRaw에
  `sjm_state` 섀도우 필드(라이브 게이트 미적용) → 30일 불일치·성과 비교 후 승격 판단.
  **섀도우 30일이 필요하므로 일찍 시작할수록 좋다** (§1 대기 항목이 되기 전에 착수).
- **공수**: 중. 기대효과 최대(리서치 P1).

### ❌ R4b. fng 물타기 제거 walk-forward 검증 — 기각 (2026-07-15 실측)
> **2026-07-15 종결**: WF 6윈도에서 0.15단일 양의윈도 4/6→3/6 악화, 0.40단일은 평균은
> 높으나 포트폴리오 표준편차 4.34→5.92·최악 윈도 손실 확대 — 견고성 미달. **현행 3단
> 유지 확정.** 상세: [return-improvement-priorities-20260715](return-improvement-priorities-20260715.md) §0a.
- **발견**: fng_optimize(P-A on, master_20260710) 재그리드에서 단일 트랜치 0.15(물타기 제거)가
  종가자산 1위(1.0339, MaxDD -1.7%). 현행 3단(1.0214, -3.0%)보다 Δ+0.55%p + MaxDD -1.3%p 개선.
  **해석**: P-A익절이 이익 방향을 조기 포착 → 추가 트랜치(-3%/-6%)의 평균회귀 역할이 감소.
- **검증**: `walk_forward_validate.py`에 `FNG_CONTRARIAN_PRICE_TRANCHES = S15`(단일 0.15) config
  추가 → 6윈도에서 현행 3단보다 일관 우위 확인 후 배포.
- **공수**: 소. 단, 물타기 전체 제거는 아키텍처 변경이라 신중하게.

### R5. P7: FNG 지속기간 피처 (`fng_days_below_30`)
- fng 개선 연장선 — 공포 1일차(뉴스 쇼크) vs 소진 국면(N일 지속) 구분 사이징/게이트.
  parquet 파생 컬럼 + regimeRaw 노출 + 백테스트. FNG 히스토리 전량 보유라 수집 작업 없음.
- **공수**: 소~중.

### ✅ R6. P6: 시간대 시즌럴리티 진단 — 종결 (2026-07-15 실측, 엣지 없음)
> hour별 스프레드가 왕복 비용과 동일 자릿수·거래 레벨 표본 부족 — 승격 조건 미달.
> 스크립트(`seasonality_diag.py`) 보존, 분기 후 재실행만. 상세: [return-improvement-priorities-20260715](return-improvement-priorities-20260715.md) §0b.
- 기존 라이브·백테스트 트레이드를 진입 UTC hour·요일별 성과 분해. 데이터 전부 보유.
  유의 패턴 발견 시에만 소프트 사이징(×0.7 등) 실험으로 승격.
- **공수**: 소(스크립트 1개).

### R8. MFE/MAE 정밀화 (1m 데이터 활용)
- 현재 4h봉 기반(보수 추정). `arena_realtime_feature_bars`(1분, 2.5만행)에 mid/last가
  있으면 라이브 기간 MFE/MAE를 1분 정밀도로 — 익절·트레일 파라미터의 근거 정밀화.
- **공수**: 소(arena-status 확장). 우선순위 낮음(방향은 4h로도 충분).

### R9. 중장기 (리서치 P4/P5/P8 — 착수 조건 명시)
- **P4 메타라벨링**: 백테스트 트레이드 → triple-barrier 라벨 데이터셋 파이프라인 구축은
  지금 가능. 모델 학습은 R1(파케이 갱신) + 표본 확대 후.
- **P5 스테이블코인 거래소 넷플로우**: morning-brief `exchange_outflow.py` 구현 — 소스
  결정(DefiLlama/무료 티어) 선행. 아레나가 아닌 파이프라인 작업.
- **P8 MAB 메타 포트폴리오 섀도우**: 독립 트랙레코드 원칙과 충돌하지 않는 7번째
  가상 트랙. 우선순위 최하.

---

## §3. 인프라·프로세스 개선 (트레이딩 로직 외)

| 항목 | 내용 | 공수 | 상태 |
|---|---|---|---|
| **모니터링 루틴화** | `/arena-status`를 주 1회 자동 실행(스케줄 루틴)해 요약을 받아보기 — 관찰 항목(§1)을 사람이 기억할 필요 없게 | 소 | ❌ 미착수 |
| 백테스트 비용 정합 | `BacktestSettings.slippage_bps=0` vs 라이브 왕복 ~13bps — 시나리오 기본값 재점검 | 소 | ❌ 미착수 |
| 대시보드 close_reason | `target_exit` 등 신규 청산 사유가 arena.sovereignwon.com에 표기되는지 확인 | 소 | ❌ 미착수 |
| gate_block_rates 정기화 | 분기 1회 재실행해 dead weight 조건 변화 추적 (직전 실행: macd `macd_hist_positive`·`rsi_below_long_max`가 dead weight 후보) | 소 | ❌ 미착수 |
| 스킬 유지보수 | 스키마 변경 시 SKILL.md 갱신 규약 준수 (박제 스키마 드리프트 방지) | 상시 | 상시 |

---

## 현행 실행 순서 (2026-07-11 업데이트)

```
완료     R1(파케이) → R7(WF) → R2(EWMA배선·off) → R4(ts60/mh36)
지금     R3 SJM 섀도우 착수 (30일 시계 — 가장 시급)
         R4b fng 물타기 제거 WF 검증 (발견→검증→배포 or 기각)
병행     §3 모니터링 루틴화
그 다음  R5 FNG 지속기간 → R6 시즌럴리티 → R8 MFE/MAE
관찰만   §1 전 항목 (주간 /arena-status로 자동 확인)
```

**요지**: 알고 파라미터 튜닝은 표본 대기가 맞지만, (1) 검증 기반의 정확도(R1·R7),
(2) 전 알고 공유 레이어(R2 사이징·R3 레짐), (3) 프로세스 자동화(§3)는 시장과 무관하게
지금 진전시킬 수 있다.
