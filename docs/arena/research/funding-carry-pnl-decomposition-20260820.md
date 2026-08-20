# funding_carry 손익 분해 — 가격손익/펀딩비 전용 컬럼 분리 기록 (2026-08-20)

## 배경

사용자가 대시보드에서 `funding_carry`(v43, [설계 문서](funding-carry-sleeve-design-20260818.md)) ETH
선물숏 다리가 -20%대로 찍힌 걸 보고 "오류 아니냐"고 문의. 확인 결과 델타중립 구조(같은 자산의
현물롱 다리가 정확히 반대로 +20%대라 두 다리를 합치면 가격변동분은 상쇄되고 펀딩비만 순증)라
정상 작동이었음 — ETH가 이틀 새 +20% 급등한 타이밍에 우연히 크게 도드라져 보였을 뿐.

이어진 논의에서 사용자가 핵심을 짚음: "가격손익과 펀딩비가 `ret_pct` 하나에 섞여 있으면, 이
전략이 실제로 펀딩비를 얼마나 벌고 있는지 검증할 방법이 없다." 코드 확인(`positions.py
close_position()`) 결과 정확한 지적이었음 — `funding_pct`는 계산은 하지만
`ret_pct += funding_pct`로 즉시 합산해버려 분리 기록이 전혀 없었다. 계산 자체는 틀리지
않음(`arena_funding_rates` 실측으로 정확성 확인 완료) — 문제는 분리 저장이 안 되는 것.

funding_carry의 존재 이유가 정확히 이 펀딩비 수취인데, 그걸 사후에 분해해서 검증할 방법이
없었다는 건 이 알고 자체의 성패를 판정할 수단이 없었다는 뜻 — 사소한 로깅 누락이 아니라
이 슬리브의 감사가능성(auditability) 결함이었음.

## 구현

**1차 시도**: 세션이 "Supabase MCP 미인증"으로 잘못 표시돼 있어(stale 안내, `claude mcp list`로
직접 확인한 결과 실제로는 이미 connected 상태였음이 나중에 드러남) DDL이 불가능하다고 판단,
기존 `signal_reason`(jsonb) 필드에 `price_pnl_pct`/`funding_pnl_pct`를 read-merge-write로
우회 기록(`scale_in_position()`이 이미 쓰는 것과 동일 패턴).

**최종 구현**: `mcp__claude_ai_Supabase__apply_migration`이 정상 동작함을 재확인한 뒤 정식
컬럼으로 교체:

```sql
ALTER TABLE public.paper_positions
  ADD COLUMN IF NOT EXISTS price_pnl_pct double precision,
  ADD COLUMN IF NOT EXISTS funding_pnl_pct double precision;
```

`positions.close_position()`을 두 컬럼에 직접 쓰도록 변경 — jsonb 우회(쓰기 2회: 메인 update +
signal_reason update)였던 걸 메인 update 1회로 통합해 더 단순하고 효율적. `ret_pct`(기존 컬럼,
전체 집계·대시보드가 참조)는 그대로 `price_pnl_pct + funding_pnl_pct` 합산값을 유지해 하위호환
깨짐 없음 — `paper_positions.ret_pct = price_pnl_pct + funding_pnl_pct`가 항상 성립한다.

perp 포지션이 아니면(`product_type in (None, "spot")`) `funding_pnl_pct = 0.0`으로 그레이스풀
초기화.

## 검증

신규 테스트 `test_close_position_records_price_and_funding_pnl_breakdown`
(`tests/test_arena_positions_perp_funding.py`) — 숏 포지션 청산 시 update payload에
`price_pnl_pct`/`funding_pnl_pct`가 정확히 분리 기록되고, 둘의 합이 `ret_pct`와 일치하는지
확인. arena 테스트 전체(409개) 통과, ruff clean.

## 배포

EC2에 배포 완료 — 이 세션은 SSH 22 아웃바운드가 막혀 있어 AWS SSM Session Manager
(`aws ssm send-command`, gzip+base64로 `positions.py` 전송) 경유. 컴파일 확인 후
`arena.service` 재시작, 재시작 직후 로그에 에러 없음 확인.

## 영향 범위

- `PARAMS_VERSION` 무변경 — 트레이딩 로직·신호 판단과 무관, 기록(persistence) 계층만 변경.
- 기존에 이미 closed 상태인 129건 포지션은 두 컬럼이 NULL(소급 백필 안 함). 이 커밋 이후 새로
  닫히는 포지션부터 채워진다. funding_carry의 현재 열려있는 4개 다리(BTC/ETH 각 2개, 최소
  14일 보유)가 닫힐 때 처음으로 실제 값이 기록된다.
- 대시보드(`arena/index.html`)에 이 분해값을 노출하는 건 이번 스코프에 포함하지 않음 — 지금은
  DB에 저장만 되고 화면엔 안 보인다. 필요시 별도 작업.
