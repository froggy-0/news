# 실행게이트 depth 임계값 자산별 재보정 (2026-08-14)

## 배경

execution_gate.py 라이브 승격을 검토하던 중, `arena_execution_gates`(최근 1개월, 페이지네이션
전량 조회) 실측에서 SOL의 실신호 거부율이 62.5%(35/56)로 BTC(24.5%, 8/7 이후)·ETH(0%)보다
압도적으로 높다는 걸 발견. 거부 사유 전부가 `depth_too_thin`이었고, `min_depth_10bp_usd
=$1,000,000`(`parameters.EXEC_GATE_MIN_DEPTH_10BP_USD`)가 **BTC 하나로 캘리브레이션된
전역 상수**를 3개 자산에 그대로 적용하고 있었다 — SOL은 원래 절대 유동성이 BTC보다 작은
자산이라, "체결 조건이 나빠서"가 아니라 "SOL이라서" 거의 항상 걸리는 구조였다.

## 실측 (2026-07-31 depth limit 수정 이후만, `scripts/analysis/exec_gate_depth_calibration.py`)

⚠️ 2026-07-30 이전 데이터는 REST `/depth limit=20` 시절 값(과소추정 버그, 별건 수정완료)이라
섞으면 분포가 이중모드로 왜곡됨 — 반드시 그 이후만 사용.

| 자산 | n | min | p5 | median | 구 threshold 대비 margin |
|---|---:|---:|---:|---:|---:|
| BTC | 606 | $2.93M | $4.09M | $5.69M | 2.93x |
| ETH | 324 | $1.07M | $1.20M | $1.57M | 1.07x(마진 7%, 위험) |
| SOL | 324 | $241K | $315K | $477K | 0.24x(**항상 미달**) |

post-fix 데이터에서 SOL의 `min(bid,ask)`가 $1M을 단 한 번도 넘은 적이 없다 — "가끔 얇다"가
아니라 "SOL은 구조적으로 항상 이 기준 미달"이었던 것.

## 조치: 자산별 임계값(BTC 마진 원칙 재적용)

BTC는 관측 최소값 대비 ~2.9x 여유폭을 두고 설계된 값(자산의 "정상 범위에서는 절대 안 걸리고
진짜 이상 상황에만 반응"하는 안전망 성격)이었다는 걸 역산해, 동일 원칙을 ETH/SOL에도 적용:

```python
EXEC_GATE_MIN_DEPTH_10BP_USD_BY_SYMBOL = {
    "BTCUSDT": 1_000_000.0,  # 기존값 유지 — 이미 안전(2.9x)
    "ETHUSDT": 400_000.0,    # 관측 min $1.07M 대비 2.7x
    "SOLUSDT": 80_000.0,     # 관측 min $241K 대비 3.0x
}
```

과거 데이터 재시뮬레이션: SOL 거부율 100%(post-fix 구간 기준)→0%, BTC/ETH 불변(둘 다 0%→0%).

## 배포 중 발견한 2차 버그 (같은 세션, 배포 직후 실측 검증으로 발견)

1차 수정(`scheduler._execution_gate_policy(symbol)`을 자산별 임계값으로 배선)을 배포한 직후
곧바로 라이브 데이터로 확인했더니, SOL의 `feature_snapshot.depth_score`가 여전히 **구
전역값($1M) 기준**으로 나오고 있었다(0.524 = $524,287/$1,000,000 — 새 임계값 $80,000 기준
이었다면 6.55가 나와야 함).

원인: `execution_gate._depth_score()`는 `features`에 `depth_score`가 이미 있으면(explicit)
그 값을 그대로 쓰고 `policy.min_depth_10bp_usd`를 무시한다. 그런데 `scheduler.
_book_execution_features()`가 매 사이클 depth_score/expected_slippage_bps를 **선계산**해
`config.EXEC_GATE_MIN_DEPTH_10BP_USD`(전역값)로 이미 정규화해 넣고 있었음 — policy 레벨
수정이 이 선계산 경로를 우회하지 못했던 것. `expected_slippage_bps`도 같은 전역값으로 계산된
depth_penalty가 섞여 있어 SOL은 실제보다 부풀려진 슬리피지 추정치를 쓰고 있었다(별건이지만
같은 근본원인).

**수정**: `_book_execution_features()`에 `min_depth_10bp_usd` 매개변수 추가(기본값=기존 전역
상수, 하위호환), 신규 헬퍼 `_min_depth_10bp_usd_for_symbol(symbol)`로 두 지점
(`_execution_gate_policy`·`_book_execution_features` 호출부) 모두 동일 소스에서 조회하도록
통일. 재배포 후 재검증은 다음 4h 사이클에서 확인 예정(즉시 확인은 회귀 테스트로 대체).

## 검증

- `scripts/analysis/exec_gate_depth_calibration.py`: 과거 데이터 재시뮬레이션(위 결과).
- 신규 테스트 3건(`tests/test_arena_execution_gate.py`): 자산별 policy 배선 확인, SOL 정상
  유동성이 신 임계값은 통과·구 임계값은 걸리는 회귀 확인, `_book_execution_features()`의
  depth_score가 명시로 넘긴 임계값을 실제로 쓰는지 확인(2차 버그의 회귀 가드).
- arena 테스트 242개 통과. EC2 배포·재시작 2회(1차 수정 + 2차 버그 수정) 완료, 에러 없음.

## 현재 상태

`ENABLE_ARENA_EXECUTION_GATE_LIVE=False` 유지 — 이 재보정은 **승격 전 필요조건 하나를
해소**한 것이지 승격 자체는 아니다. 남은 절차: (1) 새 임계값으로 1~2주 라이브 shadow
재확인(특히 SOL 거부율이 정상 범위로 안정됐는지), (2) BTC 자체는 8/7 이후 24.5% 거부율로
P8(2026-07-26) 재시뮬레이션 수치(22.1%)와 일치해 검증된 상태 유지, (3) "게이트 승격=표본 수
감소"라는 트레이드오프는 여전히 사용자 결정 필요(2026-08-14 이전 턴에서 지적).

## 부수 발견 (미해결, 조치 안 함)

`realtime_market.py`(1분 WS depth 수집기, 현재 BTC만 가동)의 `_expected_slippage_bps()`도
동일하게 `parameters.EXEC_GATE_MIN_DEPTH_10BP_USD`(전역값)를 직접 참조한다. 이 수집기는
`depth20@100ms`(상위 20레벨만) 스트림 기반이라 이미 알려진 별도 한계(2026-07-30 문서: 10bp
밴드의 5~6%만 커버, diff-depth 스트림+로컬 오더북 재구성 필요)가 있어 이번 세션에서 ETH/SOL로
확장하지 않기로 결정함(확장했다면 알려진 버그를 3자산으로 그대로 복제했을 것 — 로컬 dry-run
테스트로 사전에 확인). 이 경로를 고칠 때(별도 스레드) 심볼별 임계값도 함께 반영 필요.
