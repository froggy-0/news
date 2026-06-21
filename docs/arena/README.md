# BTC Signal Arena Docs

작성일: 2026-06-19

이 디렉터리는 BTC Signal Arena의 현재 운영 상태, 아키텍처, 연구 검증, 제품 방향을 한곳에서 추적한다.

## 빠른 진입점

| 문서 | 내용 | 먼저 읽을 상황 |
| --- | --- | --- |
| [overview/next-session-handoff.md](overview/next-session-handoff.md) | 다음 세션 시작 시 읽을 순서, 현재 운영 확인 명령, 다음 작업 | 새 세션에서 현황 파악 |
| [overview/current-state.md](overview/current-state.md) | 현재 상태, 지금까지 한 일, 결정, 고민, 남은 일 | 전체 맥락 파악 |
| [overview/decision-log.md](overview/decision-log.md) | 주요 의사결정과 이유 | 왜 이렇게 설계했는지 확인 |
| [architecture/system-map.md](architecture/system-map.md) | 코드, 데이터 흐름, DB 객체, migration 순서 | 구조/영향 범위 파악 |
| [architecture/data-lake-v0.md](architecture/data-lake-v0.md) | raw/derived/decision 데이터레이크 구조 | 수집/DB 구조 변경 전 |
| [research/research-mart-v1.md](research/research-mart-v1.md) | strategy/feature registry와 decision mart | 분석 mart 변경 전 |
| [research/backtest-framework-v1.md](research/backtest-framework-v1.md) | 백테스트, 검증 루브릭, 저장/검증 명령 | 백테스트/워크포워드 작업 전 |
| [research/frequency-research-v1.md](research/frequency-research-v1.md) | 4H/1H/15m profile, 수집, 비용 모델, shadow 운영 | 빈도/거래 횟수 실험 전 |
| [research/realtime-execution-gate-v1.md](research/realtime-execution-gate-v1.md) | 실시간 market observation, 체결 품질 gate, no-trade 원장 | 실시간 수집/조건부 매매 작업 전 |
| [research/realtime-risk-trigger-v1.md](research/realtime-risk-trigger-v1.md) | 1분 microstructure 기반 risk state, entry block/exit candidate shadow | 급등락/급락 리스크 대응 전 |
| [reference/parameter-inventory.md](reference/parameter-inventory.md) | 파라미터, 단위, 기본값, 리스크 영향 | 파라미터 변경 전 |
| [operations/access-runbook.md](operations/access-runbook.md) | 현재 EC2/Supabase 접속, 상태 확인, 조회 명령 | 서버/DB 상태 확인 |
| [operations/deploy-runbook.md](operations/deploy-runbook.md) | EC2 배포/재시작/검증 절차 | 배포/장애 대응 |

## Product

| 문서 | 내용 |
| --- | --- |
| [product/vision.md](product/vision.md) | 비전과 장기 목표 |
| [product/roadmap.md](product/roadmap.md) | Phase 0~4 로드맵 |
| [product/product-requirements.md](product/product-requirements.md) | 제품 요구사항 |
| [product/business-model.md](product/business-model.md) | 수익화와 사업 모델 |

## 현재 판정

- 운영 경로: EC2 `src/arena`가 primary.
- 거래 기준: 현재 live/paper 알고리즘과 거래 원장은 **현물 spot long/flat**만 허용한다.
- raw `short` 신호는 신규 숏 포지션이 아니라 long 청산 또는 no-trade 판단 재료다.
- derivatives/perp-style long/short, funding/OI/basis/mark price는 research/shadow/backtest 전용이며 실거래 승격 대상이 아니다.
- Lambda arena 경로: 신규 개선 대상에서 제외. EC2와 동시 활성화하면 중복 거래 위험.
- 데이터레이크: raw OHLCV, macro snapshot, indicator snapshot, decision ledger 분리 완료.
- 전략 재현성: `strategy_version`, `params_snapshot`, `indicator_snapshot`, `macro_snapshot`, `data_timestamp` 저장 완료.
- 리스크 레이어: `portfolio-risk-v1` DB 적용 및 EC2 재배포 완료.
- 백테스트: baseline replay, validation, portfolio risk replay 저장 구조 완료.
- Frequency research: 4H live 유지, 1H/15m research profile과 비용 mart 구현 완료. 1H/15m raw backfill 저장 완료.
- Realtime execution gate: 실시간 feature collector와 shadow execution gate 구현 완료. SQL 적용 후 collector enable 가능.
- Realtime risk trigger: 1분 risk state와 risk event shadow 원장 구현 완료. `ENABLE_ARENA_REALTIME_RISK_LIVE=false` 기본 유지.
- Spot semantics: `arena-spot-v3`, `arena-params-v14` 기준. legacy synthetic short는 `legacy_perp_sim`으로 분리한다.
- 파라미터 튜닝: 아직 금지. 현재 표본은 116 bars / 8 trades로 부족.

## 문서 정리 원칙

- Arena 관련 문서는 `docs/arena` 아래에 둔다.
- 과거 Morning Brief, sentiment-join, frontend, provider 문서는 기존 디렉터리에 유지한다.
- 발표 자료나 과거 연구 산출물은 Arena 운영 문서와 섞지 않는다.
- `.DS_Store`, 일회성 로컬 로그, secret 값이 담길 수 있는 문서는 저장하지 않는다.
