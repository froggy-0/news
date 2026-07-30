# Palazzi (2025), "Trading Games: Beating Passive Strategies in the Bullish Crypto Market", Journal of Futures Markets

## 무엇에 관한 논문인가
암호화폐 **페어트레이딩**(공적분 기반, Engle-Granger + Z-score 진입, 변동성 스케일 트레일링스톱,
D(L)/R(L)/S(L) 열화·과적합 진단 프레임워크).

## 얻은 인사이트
- 방법론 자체(공적분 페어, Z-score 신호)는 **2자산 이상 상대가치 전략** 전용 — 아레나는
  단일자산(BTC) 현물 롱/플랫 알고 6개라 구조적으로 적용 대상이 아님.
- 열화/과적합 진단 프레임(D/R/S)은 아이디어로는 흥미롭지만, 아레나는 이미 DSR/PBO
  (`validation_stats.py`)로 유사한 역할을 하고 있어 중복.

## 적용 여부
**미적용.** 전략군 불일치(pairs vs single-asset directional)로 판단. 숏 슬리브나 페어 전략을
도입할 계획이 생기면 재검토 대상.
