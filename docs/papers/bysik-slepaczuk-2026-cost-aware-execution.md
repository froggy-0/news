# Bysik & Ślepaczuk (2026), arXiv:2606.00060 — ML 예측거래의 cost-aware execution filter

## 무엇에 관한 논문인가
XGBoost/LSTM/iTransformer로 수익률 예측 후, `|forecast| > λ·cost·turnover` 조건으로 거래를
필터링하는 비용인식 실행필터(H2). λ 민감도 그리드(Table 16), 27-fold walk-forward, paired
circular block-bootstrap 통계검정. 부차적으로 피처강화(H3, TA+EGARCH mixed), 모델 아키텍처
비교(H4), 손실함수(H5), 모델선택기준(H6)도 다룸.

## 얻은 인사이트 + 실제 적용
- **H2(cost-aware filter) 하나만 아레나 `execution_gate.py`(ecr_multiple)와 구조적으로 대응** —
  나머지(H3~H6)는 ML 예측모델 전용이라 룰기반 아레나엔 매핑 안 됨.
- 논문의 λ 그리드를 그대로 재현(`scripts/analysis/exec_gate_ecr_sensitivity.py`, 20개월
  사후필터) → **ecr_multiple은 0.5~5.0 전 구간 non-binding**(거부율 0~2.1%) 확인. P8
  (2026-07-26) 수정 이후 알고별 실제 목표가 기반 기대수익이 비용 대비 이미 압도적으로 커서
  이 레버는 더 조정할 의미 없음.
- 이 재현 과정에서 실행게이트의 **진짜 살아있는 조건(오더북 depth)**을 실측하다 진짜 버그
  발견: `scheduler._fetch_depth_snapshot()`가 REST `/depth limit=20`을 써서 BTCUSDT 10bps
  밴드의 5~6%만 커버 → depth를 실제값의 ~1.5~2%(약 60배)로 과소추정, `depth_too_thin`·
  `slippage_too_high` 오탐 유발. `limit=1000`으로 수정, 라이브 검증 완료
  (자세한 내용: `docs/arena/research/execution-gate-depth-underestimation-fix-20260730.md`).
- §6.3 폴드별 안정성(3개월 창 연환산 시 mean이 극단왜곡, median이 더 신뢰성 있다는 경고)을
  아레나 자체 walk-forward 스크립트에도 같은 함정이 있는지 점검 — 아레나는 애초에 연환산이
  아니라 **윈도별 가중수익 합**을 그대로 쓰고 있어서 해당 함정에 걸리지 않음(고칠 것 없음).

## 적용 여부
**부분 적용.** ecr_multiple 자체는 조정 안 함(non-binding 확인만). 재현 과정에서 발견한
오더북 depth 버그는 **수정·배포 완료**(2026-07-30). 나머지 가설(H3~H6)은 아키텍처 불일치로
미적용.
