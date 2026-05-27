# Frontend Analysis Contract Rubric

## 기준 artifact

- Source: public R2 `analytics/sentiment/latest.json`
- schemaVersion: `sentiment-insight-v2`
- referenceDate: `2026-05-26`
- generatedAtUtc: `2026-05-26T23:47:00.529587+00:00`
- runId: `sentiment-join-20260526`

## 값 계약

| 항목 | 최신 값 | 프론트 반영 위치 | 판정 |
| --- | ---: | --- | --- |
| outlier filter 이후 표본 | 539일 | Story, Causality F note | pass |
| Granger 전체 검정 수 | 75 | Summary/Causality | pass |
| news_sentiment_mean -> btc_log_return lag1 | F=7.7103, p_adj=0.0178 | Causality F card | pass |
| btc_log_return -> news_sentiment_mean lag1 | F=104.2908, p_adj=0.0000 | Causality F card | pass |
| primary lag 기준 forward | lag3, F=3.7696, p_adj=0.0321 | Causality F card footnote | pass |
| primary lag 기준 reverse | lag3, F=45.1789, p_adj=0.0000 | Causality F card footnote | pass |
| full PCA hit rate | 47.5% | Story PCA 실패 | pass |
| news sentiment lag1 hit rate | 49.1% | Story PCA 실패 | pass |
| vol_regime_v2 T+7 hit rate | 61.9% | Summary/Story/Signal | pass |
| vol_regime_v2 95% CI | [52.0%, 71.8%] | Story/Signal | pass |
| vol_regime_v2 coverage | 50.6% | Story/Signal note | pass |

## 표현 루브릭

- Granger는 실제 인과 증명이 아니라 예측 선행성 검정으로 설명한다.
- `vol_regime_v2`는 거래 실행 트리거가 아니라 저위험 국면 ON/OFF 필터로 설명한다.
- `61.9%` 결과는 실전 수익 모델 확정이 아니라 이번 검증에서 우세 가능성이 관측된 결과로 표현한다.
- 거래 비용은 수수료뿐 아니라 슬리피지, 스프레드, 포지션 크기, 손익비를 포함한 추가 검증 과제로 둔다.
- 하드코딩 수치가 최신 artifact와 충돌하면 artifact 값을 우선한다.

## UI 루브릭

- Causality 매트릭스는 데스크톱에서 가로 폭을 채우고, 모바일에서는 표 성격의 가로 스크롤만 허용한다.
- feature label은 의미가 사라질 정도로 자르지 않고, 긴 라벨은 두 줄 이상으로 자연스럽게 흐르게 한다.
- 핵심 숫자 `F`, `p_adj`, `hit rate`, `CI`, `coverage`는 독립 영역에 표시하고 줄바꿈으로 잘리지 않게 한다.
- 강조 색은 유의성·상태 구분용으로만 쓰고, 투자 확정처럼 보이는 문구는 피한다.
