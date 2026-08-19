# v33/v34 잔여 3알고(fng_contrarian/vix_rsi/omnibus) 진입완화 재검증 — omnibus만 롤백 (2026-08-19)

## 배경

사용자가 "실제 자금 투입 전 신뢰도를 높이기 위해 지금 할 수 있는 방안"을 물었을 때
1순위로 제안한 항목. v38(2026-08-16)이 v33/v34 진입완화의 2×2 사후귀속을 재검증하며
`regime_trend`/`multi_factor`/`macd_momentum` 3개만 개별 분해했고, 나머지
`fng_contrarian`/`vix_rsi`/`omnibus`는 완화 유지 상태로 미검증 방치돼 있었다(v38
커밋 메시지 "4개 알고 개별로 분해"가 실제로는 3개만 다룸). regime_trend는 이 3개
중 유일하게 개별 검증돼 -7.62%p·전후반 일관으로 롤백됐다.

## 방법

1. `scripts/analysis/relaxation_cost_decomposition.py`(기존 스크립트, 6알고 전체
   2×2 분해) 재실행 — 전체 구간(2025-04~2026-07, 2700봉) 완화효과(B-D, 비용효과
   배제) 확인.
2. 음수로 나온 3개(fng_contrarian/vix_rsi/omnibus)에 대해 신규
   `scripts/analysis/relaxation_split_period_check.py`로 regime_trend 롤백 때
   쓴 것과 동일한 기준(전/후반 분할 방향 일관성) 적용.

## 결과

| 알고 | 전체 완화효과 | 전반 효과 | 후반 효과 | 일관성 | 판정 |
|---|---|---|---|---|---|
| fng_contrarian | -2.25%p | +1.23%p | -3.54%p | 불일치 | 롤백 안 함 |
| vix_rsi | -2.93%p | +0.99%p | -3.91%p | 불일치 | 롤백 안 함 |
| omnibus | -1.83%p | -1.22%p | -0.61%p | **일관** | **롤백** |

fng_contrarian·vix_rsi는 전체 구간만 보면 음수지만, 전반부에는 오히려 완화가
도움이 됐고 후반부에서만 나빠졌다 — regime_trend와 달리 "완화 자체의 구조적
해악"이 아니라 후반 국면(매크로 조건 등) 편향일 가능성을 배제할 수 없다. 동일
기준을 적용하는 이상 이 둘은 롤백 근거 부족으로 유지.

omnibus는 전반·후반 둘 다 음수 — regime_trend와 동일한 신뢰도로 해로움이
확인돼 롤백 대상.

## 조치

- `OMNIBUS_REBOUND_MIN_VOTES` 2→3(v33 이전 수준 원복).
- `FNG_CONTRARIAN_ENTRY_RELAXED_ENABLED`/`VIX_RSI_ENTRY_RELAXED_ENABLED`는
  `True` 유지(무변경).
- `PARAMS_VERSION` v43→v44.
- 신규 테스트 없음(파라미터 상수 변경만, 기존 스냅샷 테스트 버전 문자열 갱신).
  arena 전체 테스트 통과.
- EC2 배포 완료(AWS SSM Session Manager 경유, `parameters.py` 단일 파일
  gzip+base64 전송 → 컴파일 확인 → `arena.service` 재시작 → 정상 사이클 로그
  확인, 에러 0).

## 롤백

`OMNIBUS_REBOUND_MIN_VOTES`를 2로 되돌리면 v44 이전(v38~v43) 상태로 복귀.

## 남은 과제

fng_contrarian·vix_rsi의 "후반부에서만 나빠짐" 현상 자체는 원인 미상 — 매크로
국면 변화 때문인지, 완화 자체의 지연된 부작용인지 분리되지 않았다. 표본이 더
쌓이면(라이브 트랙레코드) 재검증할 가치가 있으나, 지금은 이 질문에 답할 만큼
표본이 없어 보류.
