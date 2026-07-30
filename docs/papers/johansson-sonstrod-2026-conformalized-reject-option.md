# Johansson & Sönström (2026), Machine Learning with Applications 23, 100838 — Conformalized classifiers with reject option

## 무엇에 관한 논문인가
분류기의 reject option(불확실한 인스턴스는 예측 보류) 시나리오에서, 원시 확률이든
Platt/Isotonic/Beta/Platt-Binning으로 보정한 확률이든 "이 rejection level에서 실제
정확도/정밀도가 얼마인가"를 사전 추정하면 체계적으로 편향됨을 보이고, **inductive conformal
prediction** 기반 절차(식7-8: `ε̂ = (ε-P(e))/P(s)`)로 이 추정을 검증보장(validity guarantee)
하에 정확하게 계산하는 방법(Conf)을 제안. Mondrian conformal classifier로 정밀도(precision)
추정까지 확장. 41개 벤치마크 데이터셋(DT/RF/XGBoost)에서 Conf가 모든 rejection level에서
통계적으로 유의하게 가장 정확한 추정치를 제공함을 실증.

## 얻은 인사이트
- 핵심 사상: "확률을 보정해도, 특정 reject 비율에서의 성능추정은 별도로 검증돼야 한다."
- 방법론(ICP)은 **학습된 확률적 분류기 + iid에 가까운 calibration set**을 전제 — 아레나는
  의도적으로 룰기반(해석가능성·투명 트랙레코드가 제품 핵심)이라 확률모델 자체가 없음.
- Exchangeability(교환가능성) 가정이 레짐이 바뀌는 금융시계열과 정면충돌 — 이 가정이 깨지는
  문제를 피하려고 아레나가 이미 DSR/PBO·walk-forward를 쓰고 있음(이 논문의 해법이 무의미해지는
  지점과 정확히 일치).
- calibration set 해상도(`1/(q+1)` 단위)가 알고당 20개월 거래수(35~106건)로는 세밀한 ε(0.01,
  0.05) 추정에 턱없이 부족(논문은 수백~수만 건 데이터셋 기준).
- 유일하게 가벼운 후보: 새 conformal 장치 없이, 이미 존재하는 `risk_overlay.compute_signal_
  confidence()`가 실제 승률과 상관있는지 사후-서브셋 필터링(기존 세션 기법 재사용)으로 검증 —
  다만 신호실행에 영향 없는 순수 진단값이라 이미 죽은 신호일 가능성, 표본크기 문제 동일 적용,
  최근 유사 가설(P4 등)이 전부 이 창에서 기각된 전례로 기대치 낮음.

## 적용 여부
**미적용.** 아키텍처(룰기반 vs 확률모델)·가정(exchangeability vs 비정상 시계열)·표본크기
3중으로 전이성 낮음. signal_confidence 사후검증만 시도할 경우 저비용이나 저기대값.
