# Arena 다음 세션 인계

최종 갱신: 2026-08-15

이 문서는 새 Codex 세션이 Arena의 현물·선물 실행 경로, 숏 활성화 상태, 운영
Supabase 용량 최적화 결과를 가장 먼저 복원하기 위한 기준 문서다. 저장소 루트에서
작업하고, 이 문서와 `AGENTS.md`를 읽은 뒤 필요한 세부 문서로 내려간다.

## 1. 현재 결론

- EC2 `arena.service`는 BTC/ETH/SOL의 현물 트랙과 USDM perp 트랙을 함께 실행한다.
- 현물은 `spot_long_flat`, 선물은 `usdm_perp_long_short` 원장 의미론으로 분리된다.
- 선물 롱 트랙은 운영 중이지만 **신규 숏 진입은 아직 비활성**이다.
- 숏 승격 게이트는 `(track_symbol, algo_id)` 단위이며
  `PERP_SHORT_ENABLED_TRACKS`는 현재 빈 집합이다.
- `macd_momentum`과 omnibus 숏 후보는 검증 기준을 통과하지 못해 기각했다.
- 운영 Supabase 최적화와 EC2 코드 배포는 완료됐다.
- 500 MiB 제한 대비 DB 사용량은 약 316 MiB에서 206 MiB로 감소했다.

숏을 켜는 것과 선물 트랙을 켜는 것은 별개다.
`ARENA_PERP_LIVE_ENABLED=True`는 선물 트랙 실행을 뜻하고,
`PERP_SHORT_ENABLED_TRACKS` 가입만 신규 숏을 허용한다.

## 2. 이번 변경의 운영 상태

### Supabase

| 항목 | 값 |
| --- | --- |
| project ref | `etscgpquupksucbyrvhh` |
| PostgreSQL | 17.6 |
| migration | `20260815_arena_perp_short_execution_v1.sql` 적용 완료 |
| 적용 전 DB | 330,984,595 bytes, 약 316 MiB, 한도 대비 63.1% |
| 적용 후 DB | 216,378,515 bytes, 약 206 MiB, 한도 대비 41.3% |
| 확보 공간 | 약 110 MiB |
| 예상 잔여 | 약 294 MiB |

용량 절감의 대부분은 다음 두 항목에서 나왔다.

1. `arena_run_ohlcv_bars`
   - 실행마다 공통 OHLCV를 다시 연결하던 175,574행을 제거했다.
   - 공통 `arena_ohlcv_bars`는 유지한다.
   - 실행에는 `market_data_symbol`, `input_open_time`, `input_close_time`,
     `input_bar_count`만 기록한다.

2. `arena_execution_gates`
   - 1,000레벨 `depth_bids`/`depth_asks` 원본과 중첩된 feature/risk 사본을 제거했다.
   - 판단 재현에 필요한 scalar feature, typed 결과, gate policy, risk snapshot만 남긴다.

초안에 있던 신규 범용 인덱스 6개는 운영 쿼리 통계와 현재 데이터량상 가치가 낮아
추가하지 않았다. 열린 포지션의 `(symbol, algo_id)` partial unique index는 기존 것을
재사용하고 명칭만 정리했다.

### EC2

| 항목 | 값 |
| --- | --- |
| instance | `i-080675ad97e459f49` |
| name | `kr-pr-ec2-arena-v1a` |
| public IP | `3.39.201.112` |
| service | `arena.service` |
| remote dir | `/home/ubuntu/news` |
| 배포 방식 | AWS SSM `AWS-RunShellScript` 파일 단위 배포 |
| 최신 확인 | `active/running`, `ExecMainStatus=0`, `NRestarts=0` |

원격 디렉터리는 Git checkout이 아니다. `git pull`을 전제로 하지 말고
`docs/arena/operations/ssm-deploy-fallback-20260815.md`의 절차를 사용한다.

이번에 원격 반영한 파일:

- `src/arena/data_lake.py`
- `src/arena/parameters.py`
- `src/arena/perp_policy.py`
- `src/arena/positions.py`
- `src/arena/scheduler.py`
- `src/arena/short_signals.py`
- `src/arena/slack_notify.py`

각 원격 파일의 SHA-256이 로컬과 일치했고, 원격 `compileall`과 서비스 재시작 후
최근 오류 로그가 비어 있음을 확인했다.

## 3. 데이터 공유와 분리 원칙

### 현물·선물 공통 재사용

- OHLCV와 시장 피처는 실제 거래소 티커로 공유한다.
- 예: 실행 트랙 `BTCUSDT-PERP`는 시장 데이터 심볼 `BTCUSDT`를 사용한다.
- 공통 OHLCV는 `arena_ohlcv_bars`에 한 번만 저장한다.
- 실행별 입력은 전체 bar 링크가 아니라 범위와 개수만 저장한다.

### 트랙별 분리

- `arena_runs.symbol`
- `arena_decisions`
- `paper_positions`
- 포지션 방향과 상품 의미론
- 펀딩, 마진, 청산 등 perp 전용 리스크
- 숏 활성화 권한

spot/perp 계약을 알고리즘 ID로 추론하지 않는다. 호출부가 `product_type`과
`position_semantics`를 명시해야 하며, 심볼 접미사와 계약이 맞지 않으면 포지션 생성이
거부된다.

## 4. 숏 실행 설계와 현재 판정

핵심 경로:

- `src/arena/parameters.py`: 트랙 단위 숏 allowlist
- `src/arena/short_signals.py`: 숏 전용 신호 registry와 long/short 충돌 해결
- `src/arena/scheduler.py`: 실행 트랙, 상품, 알고를 함께 확인해 숏 신호 배선
- `src/arena/perp_policy.py`: perp long/short 상태 전이
- `src/arena/positions.py`: 상품·트랙·방향 최종 방어선

현재 상태:

```python
PERP_SHORT_ENABLED_TRACKS: frozenset[tuple[str, str]] = frozenset()
PERP_SHORT_ALGORITHMS: dict[str, SignalFn] = {}
```

숏 후보를 활성화하려면 다음 두 조건을 모두 만족해야 한다.

1. `short_signals.PERP_SHORT_ALGORITHMS`에 해당 알고리즘의 독립 숏 함수를 등록한다.
2. 검증을 통과한 자산만 `PERP_SHORT_ENABLED_TRACKS`에
   `("BTCUSDT-PERP", "algo_id")` 형태로 가입한다.

알고리즘 ID만 전역으로 허용하거나 spot 신호의 `short` 결과를 그대로 perp 신규 진입에
재사용하면 안 된다.

### 기각된 후보

- `macd_momentum`: DSR 최대 0.586, bootstrap 95% CI가 모두 0을 포함해 기각.
- omnibus structural:
  - BTC `-19.29%`, PF `0.63`
  - ETH `-28.00%`, PF `0.54`
  - SOL `-11.78%`, PF `0.74`
- omnibus confirmed:
  - BTC `-9.32%`, PF `0.61`
  - ETH `-13.41%`, PF `0.49`
  - SOL `-1.27%`, PF `0.96`, CI가 0을 포함

따라서 현재 어떤 자산에도 신규 숏을 열지 않는다. 다음 후보를 연구한다면
`regime_trend`를 별도 사양으로 사전 선언하고, 자산별 walk-forward/DSR/bootstrap CI를
통과한 트랙만 제한적으로 승격한다.

## 5. 변경 파일 지도

| 경로 | 역할 |
| --- | --- |
| `src/arena/data_lake.py` | 공통 OHLCV 재사용, 실행 입력 범위 기록, gate JSON 축소 |
| `src/arena/parameters.py` | 트랙 단위 숏 게이트, 상품/실제 티커 매핑 |
| `src/arena/short_signals.py` | 숏 신호 registry와 방향 충돌 처리 |
| `src/arena/scheduler.py` | spot/perp 실행 배선과 데이터 심볼 전달 |
| `src/arena/positions.py` | product/semantics/track 무결성 및 숏 최종 guard |
| `supabase/migrations/20260815_arena_perp_short_execution_v1.sql` | 운영 적용된 스키마·정리 migration |
| `scripts/analysis/omnibus_short_backtest.py` | 공개 Binance 4H 기반 omnibus 후보 검증 |
| `docs/arena/research/spot-to-perp-phase-b-short-entry-design-20260815.md` | 상세 설계와 연구 판정 |

주의: `supabase/migrations/`는 저장소 `.gitignore` 대상이다. 이 migration은 이미 운영에
적용됐으며, 재현성을 위해 이번 커밋에서 `git add -f`로 추적해야 한다.

## 6. 새 세션의 읽기 순서

1. `AGENTS.md`
2. `docs/arena/overview/next-session-handoff.md`
3. `docs/arena/research/spot-to-perp-phase-b-short-entry-design-20260815.md`
4. `supabase/migrations/20260815_arena_perp_short_execution_v1.sql`
5. `src/arena/parameters.py`
6. `src/arena/short_signals.py`
7. `src/arena/scheduler.py`
8. `src/arena/positions.py`
9. 필요할 때만 `docs/arena/operations/ssm-deploy-fallback-20260815.md`

과거 `overview/current-state.md`와 일부 연구 문서는 역사적 맥락이지만 “spot only”처럼
현재와 다른 서술이 남아 있을 수 있다. 현재 운영 판단은 이 문서와 코드·운영 조회를
우선한다.

## 7. 검증 명령

로컬 전체 Arena 테스트:

```bash
cd /Users/giwon/code/news
env PYTHONPATH=.:src UV_CACHE_DIR=.cache/uv \
  uv run pytest tests/test_arena_*.py -q
```

정적 검사:

```bash
UV_CACHE_DIR=.cache/uv uv run ruff check \
  src/arena/data_lake.py \
  src/arena/parameters.py \
  src/arena/perp_policy.py \
  src/arena/positions.py \
  src/arena/scheduler.py \
  src/arena/short_signals.py \
  src/arena/slack_notify.py \
  scripts/analysis/omnibus_short_backtest.py \
  tests/test_arena_*.py
python -m compileall -q src/arena
git diff --check
```

이번 작업의 마지막 로컬 결과는 `277 passed`다. 경고는 프로젝트 메타데이터와 외부
라이브러리 deprecation 관련이며 이번 변경 실패가 아니다.

운영 서비스 상태는 SSM으로 읽기 전용 확인한다.

```bash
aws ssm describe-instance-information --region ap-northeast-2 \
  --filters "Key=InstanceIds,Values=i-080675ad97e459f49"
```

Supabase에서 최근 실행을 확인할 때는 spot/perp 양쪽의 입력 범위와 중복 저장 여부를
같이 본다.

```sql
select
  symbol,
  status,
  count(*) as runs,
  count(*) filter (
    where market_data_symbol is not null
      and input_open_time is not null
      and input_close_time is not null
      and input_bar_count > 0
  ) as runs_with_input_range
from arena_runs
where started_at >= now() - interval '10 minutes'
group by symbol, status
order by symbol, status;

select count(*) as redundant_run_bar_links
from arena_run_ohlcv_bars;

select
  count(*) filter (where feature_snapshot ? 'depth_bids') as depth_bids_rows,
  count(*) filter (where feature_snapshot ? 'depth_asks') as depth_asks_rows,
  count(*) filter (where gate_snapshot ? 'feature_snapshot') as nested_feature_rows,
  count(*) filter (where gate_snapshot ? 'risk_snapshot') as nested_risk_rows
from arena_execution_gates
where created_at >= now() - interval '10 minutes';
```

## 8. 변경 금지·안전 경계

- 검증 결과 없이 `PERP_SHORT_ENABLED_TRACKS`를 채우지 않는다.
- 현물의 기존 롱/플랫 의미론과 트랙레코드를 초기화하지 않는다.
- 공통 OHLCV를 spot/perp별로 다시 복제하지 않는다.
- 500 MiB 제한 아래에서 근거 없는 인덱스나 대형 JSON snapshot을 추가하지 않는다.
- 운영 DB 제약·인덱스 추가 전 기존 행 위반 여부를 먼저 확인한다.
- EC2 변경은 compile/test 후 배포하고, 재시작 뒤 active/restart count/error log를 본다.
- `.env*`, service role key, AWS/Supabase 자격증명을 읽거나 출력하지 않는다.
- `gw/`, `lambda/arena/`, `review/`, `terraform/`의 별도 사용자 작업을 이 작업과 섞지 않는다.

## 9. 다음 세션용 복사 프롬프트

아래 블록 하나를 저장소 루트에서 시작한 새 Codex 세션에 그대로 전달한다.

```text
목표: SOVEREIGNWON Arena의 현물·선물·숏 실행 상태와 Supabase 500 MiB 최적화 상태를
현재 코드와 운영 환경에서 재검증하고, 다음으로 가치가 가장 높은 안전한 작업을
설계한 뒤 요청 범위 안에서 구현·검증해줘.

컨텍스트:
- 먼저 AGENTS.md와 docs/arena/overview/next-session-handoff.md를 끝까지 읽어.
- 상세 숏 설계는 docs/arena/research/spot-to-perp-phase-b-short-entry-design-20260815.md,
  운영 migration은 supabase/migrations/20260815_arena_perp_short_execution_v1.sql을 확인해.
- 운영 Supabase project ref는 etscgpquupksucbyrvhh이고, EC2는
  i-080675ad97e459f49 / arena.service다.
- 선물 롱 트랙은 활성 상태지만 PERP_SHORT_ENABLED_TRACKS와
  short_signals.PERP_SHORT_ALGORITHMS는 비어 있어 신규 숏은 꺼져 있다.
- macd_momentum과 omnibus 숏 후보는 기각됐으므로 같은 사양을 재활성화하지 마.
- 운영 DB는 최적화 후 약 206 MiB이며 500 MiB 한도에서 불필요한 복제·인덱스·대형
  JSON을 피해야 한다.

작업 방식:
1. git 상태와 최근 관련 커밋을 확인하고 사용자 변경을 보존해.
2. 코드, 테스트, migration을 기준으로 handoff 서술이 현재와 일치하는지 확인해.
3. Supabase MCP와 AWS SSM이 연결돼 있으면 운영 상태를 읽기 전용으로 먼저 확인해.
4. 다음 변경이 필요하면 spot/perp 공통 데이터는 재사용하고, 포지션·리스크·방향처럼
   의미가 다른 것만 트랙별로 분리해.
5. 숏 후보를 연구할 경우 사양을 먼저 고정하고 자산별 비용 포함 walk-forward,
   bootstrap 95% CI, DSR을 통과한 트랙만 제안해. 통과 전에는 숏 게이트를 열지 마.
6. 변경 후 가장 좁은 테스트와 Ruff를 먼저 실행하고 영향이 넓으면
   env PYTHONPATH=.:src UV_CACHE_DIR=.cache/uv uv run pytest tests/test_arena_*.py -q까지 실행해.
7. 운영 변경을 적용했다면 서비스 active 상태, 재시작 횟수, 최근 오류 로그, 신규
   spot/perp 실행과 DB 용량을 확인해.

경계:
- .env*나 자격증명 값을 읽거나 출력하지 마.
- 현물 트랙레코드를 초기화하거나 검증되지 않은 숏을 활성화하지 마.
- gw/, lambda/arena/, review/, terraform/의 별도 작업은 건드리지 마.
- 운영에 이미 적용된 내용을 다시 적용하기 전에 migration 이력을 확인해.

결과는 결론부터 보고하고, 확인한 운영 수치, 변경 파일, 테스트 결과, 남은 위험과
다음 한 가지 행동을 명확히 정리해줘.
```

## 10. 다음 우선순위

현재 가장 합리적인 다음 연구 항목은 `regime_trend` 숏을 별도 신호로 설계하는 것이다.
다만 이는 “활성화 작업”이 아니라 사전 선언된 연구 스프린트다. 통과 자산이 없다면
숏 게이트를 계속 비워 두는 것이 완료 조건이다.
