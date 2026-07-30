# execution_gate 오더북 깊이 과소추정 버그 수정 (2026-07-30)

## 배경

`docs/arena/research/dormant-data-audit-20260726.md`가 미해결 항목으로 남겨둔 "오더북
깊이 추정 상위20레벨 한정 이슈"를, Bysik & Ślepaczuk(2026, arXiv:2606.00060)의 cost-aware
execution filter(λ)를 아레나 `evaluate_execution_gate()`(ecr_multiple)에 재현해보는
세션 중 실측으로 확인·수정했다.

## 진단

`scheduler._fetch_depth_snapshot()`가 Binance REST `/api/v3/depth?limit=20`으로
오더북을 가져와 `depth_10bp_bid/ask_usd`(±10bps 밴드 내 유동성)를 계산하는데, 실측
결과 BTCUSDT는 유동성이 너무 깊어서 **20레벨이 10bps 밴드의 5~6%밖에 못 채운다**:

```
2026-07-30 실측(mid≈$64,835): 20번째 레벨까지 거리 = bid 0.65bps / ask 0.46bps
→ 10bps 밴드 커버 실패, depth_10bp_bid/ask_usd = $98K / $616K (과소추정)
```

`limit`을 늘려가며 실측:

| limit | 마지막 레벨 거리(bid/ask bps) | 10bps 커버 | depth_10bp($) |
|---|---|---|---|
| 20(구) | 0.65 / 0.46 | ❌ | $98K / $616K |
| 100 | 2.26 / 1.68 | ❌ | $1.67M / $0.50M |
| 500 | 13.32 / 6.32 | ❌(ask 미달) | $6.27M / $3.26M |
| **1000** | 34.70 / 13.52 | ✅ | **$6.26M / $5.62M** |
| 5000 | 151.70 / 92.08 | ✅(동일) | $6.26M / $5.62M |

→ 실제 유동성 대비 **~60배 과소추정**. `EXEC_GATE_MIN_DEPTH_10BP_USD=$1,000,000`·
`EXEC_GATE_MIN_DEPTH_SCORE=0.5`·`EXEC_GATE_MAX_SLIPPAGE_BPS=8.0` 기준과 대조하면
구버전 추정치는 `depth_too_thin`(depth_score≈0.098)과 `slippage_too_high`
(depth_penalty로 expected_slippage_bps≈9.2) **둘 다 오탐**을 유발했을 것으로 확인.
세계 최고 유동성 자산인 BTCUSDT에서 이 정도 오차는 실질 시장상황과 무관한 순수
계측 버그.

## 수정

`scheduler._fetch_depth_snapshot()`의 `limit=20` → `parameters.EXEC_GATE_DEPTH_SNAPSHOT_LIMIT`
(신규 상수, 1000)로 교체. 5000까지 안 가도 1000에서 이미 완전 커버(추가 이득 없음
확인) — 불필요하게 큰 페이로드 회피. Binance weight 비용은 limit 1000에서도 10
(4H당 1회 호출이라 rate-limit 무관, 미미).

**실측 검증**: 수정 후 동일 시점 라이브 호출 — `depth_score=5.715`(구버전 대비
57배), `expected_slippage_bps≈0.001`(구버전 9.2 대비 사실상 0) — 오탐 해소 확인.

## 영향 범위 및 남은 항목

- **수정 완료**: `scheduler._fetch_depth_snapshot()`(4H 사이클 실행게이트 판정용 REST
  스냅샷) — 섀도우 전용이라 실거래 무영향, PARAMS_VERSION bump 불필요(하니스/데이터
  버그 수정, 파라미터 값 변경 아님, W1/W2와 동일 원칙).
- **미수정(별도 작업 필요)**: `realtime_market.py`의 `depth20@100ms` 웹소켓 스트림
  (1분 연속 피처바, `realtime_risk.py`·TCA가 사용) — Binance 파셜북 스트림 자체가
  5/10/20 레벨만 지원해 REST처럼 파라미터만 바꿔서 해결 불가. 깊게 하려면 diff-depth
  스트림(`@depth@100ms`, 무제한 레벨) + 로컬 오더북 유지(초기 REST 스냅샷 + 갱신 적용,
  Binance 공식 오더북 유지 가이드)로 구조 변경 필요 — 더 큰 작업, 별도 검토 대상.

## 부수 발견 (같은 세션): ecr_multiple(λ) 자체는 더 이상 조정 레버가 아님

논문의 λ 민감도 재현(`scripts/analysis/exec_gate_ecr_sensitivity.py`, 20개월 백필
사후-필터)에서 `ecr_multiple`을 0.5~5.0으로 바꿔도 6알고 전체 거부율이 0~2.1%로
사실상 non-binding임을 확인 — P8 수정(2026-07-26) 이후 알고별 실제 목표가 기반
`expected_return_bps`가 비용(13bps) 대비 이미 압도적으로 커서 이 문턱은 안 걸림.
**남은 실질 게이트 레버는 오더북/실행품질 조건**(spread/depth/slippage/latency) —
이번 depth 버그 수정이 바로 그 축.
