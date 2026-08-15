# Arena 다음 세션 인계

최종 갱신: 2026-08-15

이 문서는 새 Codex 세션이 Arena의 현물·선물 실행 경로, 숏 활성화 상태, 운영
Supabase 용량 최적화 결과를 가장 먼저 복원하기 위한 기준 문서다. 저장소 루트에서
작업하고, 이 문서와 `AGENTS.md`를 읽은 뒤 필요한 세부 문서로 내려간다.

## 1. 현재 결론

- EC2 `arena.service`는 BTC/ETH/SOL의 현물 트랙과 USDM perp 트랙을 함께 실행한다.
- 현물은 `spot_long_flat`, 선물은 `usdm_perp_long_short` 원장 의미론으로 분리된다.
- 선물 롱 트랙은 운영 중이다. **기존 6알고(`regime_trend`·`fng_contrarian`·
  `vix_rsi`·`macd_momentum`·`multi_factor`·`omnibus`)는 여전히 신규 숏 진입
  비활성**(D017 사전 DSR≥0.95 게이트 미통과) — 숏 승격 게이트는
  `(track_symbol, algo_id)` 단위, 이 6알고 조합은 `PERP_SHORT_ENABLED_TRACKS`에
  없다.
- **신규 7번째 알고 `meridian`(arena-params-v36, 2026-08-15)만 예외** — D017과
  다른 경로(D019, "리서치 종합 설계로 승격")로 처음부터 BTC/ETH/SOL 3개 perp
  트랙 전부 `PERP_SHORT_ENABLED_TRACKS`에 등록돼 롱/숏 양방향 실거래 중이다.
  perp 트랙 전용(`ALGORITHM_TRACK_SCOPE`, spot 미실행). 상세:
  [meridian-combined-long-short-design-20260815.md](../research/meridian-combined-long-short-design-20260815.md),
  decision-log.md D019.
- §1원칙3 순서대로 기존 6개 알고(`macd_momentum`·omnibus·`regime_trend`·
  `multi_factor`·`vix_rsi`·`fng_contrarian`) 전부 검증했고 전부 검증 기준을
  통과하지 못해 기각했다(Phase B 1순환 완료, 2026-08-15).
- Phase B 1순환 직후 "왜 하락장에서도 숏 엣지가 하나도 안 나왔는가"를 학술
  문헌으로 조사·정리했다
  ([short-entry-asymmetry-literature-review-20260815.md](../research/short-entry-asymmetry-literature-review-20260815.md)),
  이어서 2순환으로 그 문헌이 제시한 두 가설을 이 프로젝트 데이터로 직접
  검정했다(같은 날, 설계 문서 §15~§17): (a) GJR-GARCH(1,1) 진단 — BTC/ETH/SOL
  daily·4H 6개 테스트 전부 비대칭 계수 유의수준 미달(null, 역방향·정방향
  레버리지 효과 둘 다 미확인). (b) macd_momentum 숏에 모멘텀 고유 변동성
  사이징(Barroso & Santa-Clara 2015) 추가 — DSR이 사이징과 무관하게 baseline과
  완전 동일(0.45~0.53, 사이징이 거래 분포 자체를 못 바꾸므로 원리적으로 불변),
  채택 기준 전부 미달로 기각.
- **Phase B 숏 연구 종결(2026-08-15)** — 거울반전(1순환)·문헌기반 재해석·
  모멘텀크래시 사이징 처방까지 전부 시도했으나 숏 엣지를 만들지 못했다.
  선물 트랙은 무기한 롱온리로 확정한다. `vix_rsi`(ETH, DSR 0.934로 근접미달)만
  별개 트랙으로 표본 축적 대기(그리드 재탐색 없이 관찰만).
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
- `regime_trend`(strict_8of8 / relaxed_4of8 두 변형, `scripts/analysis/regime_trend_short_backtest.py`):
  - BTC strict `-1.18%`(PF 0.56) / relaxed `-2.01%`(PF 1.01, DSR 최댓값 0.312)
  - ETH strict `-0.05%`(PF 0.71) / relaxed `-0.16%`(PF 0.95)
  - SOL strict `+0.14%`(PF 0.98, CI [-5.15%,+6.47%]) / relaxed `-5.78%`(PF 0.76, 전후반 둘 다 손실)
  - 6셀 전부 DSR(n_trials=2) 0.95 미달, CI 전부 0 포함 — 기각(상세: 설계 문서 §10).
- `multi_factor`(direction_soft / direction_hard_reinterpreted 두 변형,
  `scripts/analysis/multi_factor_short_backtest.py`):
  - direction_soft(레짐 소프트투표, veto 유지): BTC `+2.12%`(DSR 0.443) / ETH `+1.11%`
    (DSR 0.377) / SOL `+0.94%`(DSR 0.386) — 3자산 전부 방향은 양이나 기준 미달.
  - direction_hard_reinterpreted(레짐 hard+ETF유출·LSR과밀 veto→팩터 편입): ETH
    `-24.59%`(CI 전부 음수, DSR 0.000)로 명확히 악화.
  - 6셀 전부 기각(상세: 설계 문서 §11).
- `vix_rsi`(veto유지 / veto제거, `scripts/analysis/vix_rsi_short_backtest.py`, VIX
  고조+RSI과열 별개 가설로 설계): ETH veto유지가 `+11.09%`(PF 2.16, DSR **0.934**,
  CI [-0.37%,+22.07%])로 6개 알고 전체 중 채택선(DSR≥0.95, CI 하한>0)에 가장 근접했으나
  **문자 그대로는 미달**. BTC는 두 변형 다 음수라 3자산 동시 통과는 아니다(상세:
  설계 문서 §12).
- `fng_contrarian`(veto유지 / veto제거, `scripts/analysis/fng_contrarian_short_backtest.py`,
  FNG>70 탐욕 별개 가설로 설계): SOL veto유지가 `+6.39%`(DSR 0.760)로 가장 좋지만
  기준 미달, BTC/ETH는 음수. **구현 중 `backtest.py`의 fng 전용 이익포착 로직
  (`FNG_TARGET_EXIT_ENABLED`)이 direction을 확인하지 않아 숏에 적용 시 항상 손실
  확정으로 청산되는 결함을 발견**(현재 fng_contrarian은 롱만 반환해 라이브·기존
  테스트엔 영향 없는 도달 불가능 경로) — 스크립트에서 해당 플래그를 프로세스 로컬로
  비활성화하고 재실행해 정상 결과를 얻었다(상세: 설계 문서 §13).

**Phase B 1순환 완료(2026-08-15)** — 6개 알고 전부 §4 채택 기준(DSR≥0.95, CI 하한>0,
전/후반 부호일관)을 문자 그대로 충족하지 못해 `PERP_SHORT_ENABLED_TRACKS`는 여전히
빈 집합이다. `vix_rsi`(ETH)만 근접 미달이라, 최종 판단(ETH 단일자산 승격 여부·
`backtest.py`의 fng 결함 정식 수정 여부)은 사용자에게 남긴다(상세: 설계 문서 §14).

**Phase B 2순환 완료(2026-08-15, 같은 날 후속)** — 1순환 직후 문헌 조사가 제시한
두 가설(역방향 레버리지 효과 진단, macd_momentum 모멘텀 고유 변동성 사이징)을
검증했으나 둘 다 기각(설계 문서 §15~§17). GJR-GARCH는 null(레버리지 효과 방향
자체가 안 나타남), 모멘텀 vol 사이징은 DSR이 baseline과 완전 동일해 채택 기준에
못 미쳤다. **Phase B는 여기서 종결** — 6개 알고 거울반전·문헌기반 재해석·
모멘텀크래시 사이징까지 전부 실패했다는 게 최종 결론이며, 선물 트랙은 무기한
롱온리로 확정한다. `vix_rsi`(ETH)만 §14 옵션2대로 별도 관찰 대상 유지.

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
| `scripts/analysis/regime_trend_short_backtest.py` | Supabase macro 백필 기반 regime_trend 후보 검증(strict/relaxed 2변형) |
| `scripts/analysis/multi_factor_short_backtest.py` | multi_factor 후보 검증(direction_soft/hard_reinterpreted 2변형) |
| `scripts/analysis/vix_rsi_short_backtest.py` | vix_rsi 후보 검증(veto유지/제거 2변형) — `_momentum_not_improving` 헬퍼도 여기 정의, fng 스크립트가 재사용 |
| `scripts/analysis/fng_contrarian_short_backtest.py` | fng_contrarian 후보 검증(veto유지/제거 2변형), fng 전용 이익포착 로직의 direction 미분기 결함 발견·우회 |
| `scripts/analysis/gjr_garch_leverage_diagnosis.py` | 2순환 §3-1 — GJR-GARCH(1,1) 비대칭 계수 진단(전략 아님, 진단 전용) |
| `scripts/analysis/macd_momentum_short_vol_sizing_backtest.py` | 2순환 §3-2 — macd_momentum 숏 모멘텀 고유 변동성 사이징 검증(veto제거 고정, 사이징 축만 신규) |
| `docs/arena/research/short-entry-asymmetry-literature-review-20260815.md` | Phase B 1순환 직후 학술 문헌 조사(모멘텀 크래시·레버리지 효과), 2순환 제안 |
| `docs/arena/research/spot-to-perp-phase-b-short-entry-design-20260815.md` | 상세 설계와 연구 판정(§8~§14 1순환, §15~§17 2순환·최종 종결) |
| `docs/arena/overview/decision-log.md` | D017에 1순환(6개 알고)·2순환(문헌기반 진단·사이징) 근거와 종결 결론 반영 |

주의: `supabase/migrations/`는 저장소 `.gitignore` 대상이다. 이 migration은 이미 운영에
적용됐으며, 재현성을 위해 이번 커밋에서 `git add -f`로 추적해야 한다.

## 6. 새 세션의 읽기 순서

1. `AGENTS.md`
2. `docs/arena/overview/next-session-handoff.md`
3. `docs/arena/research/spot-to-perp-phase-b-short-entry-design-20260815.md`
4. `docs/arena/research/short-entry-asymmetry-literature-review-20260815.md`
   (2순환 제안 문서 — 2026-08-15 같은 날 §3-1·§3-2 모두 실행·기각 완료, Phase B
   종결. 재탐색 근거로 쓰지 말 것)
5. `supabase/migrations/20260815_arena_perp_short_execution_v1.sql`
6. `src/arena/parameters.py`
7. `src/arena/short_signals.py`
8. `src/arena/scheduler.py`
9. `src/arena/positions.py`
10. 필요할 때만 `docs/arena/operations/ssm-deploy-fallback-20260815.md`

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

- **기존 6알고**(`regime_trend`·`fng_contrarian`·`vix_rsi`·`macd_momentum`·
  `multi_factor`·`omnibus`)는 D017 사전 DSR≥0.95 검증 결과 없이
  `PERP_SHORT_ENABLED_TRACKS`를 채우지 않는다. `meridian`은 D019 경로로 이미
  등록돼 있다(예외이지 선례 확장 아님 — 다른 알고나 다른 신규 알고에 D019를
  적용할지는 매번 별도 사용자 결정 필요).
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
- 선물 롱 트랙은 활성 상태. 기존 6알고는 PERP_SHORT_ENABLED_TRACKS에 없어
  신규 숏이 꺼져 있지만, **신규 7번째 알고 `meridian`(2026-08-15, D019 경로)은
  3개 perp 트랙 전부 숏 등록·실거래 중**이다 — 아래 결론과 모순 아님(§1 참고,
  기존 6알고 얘기다). meridian 설계:
  docs/arena/research/meridian-combined-long-short-design-20260815.md.
  대시보드(`arena/index.html`)에는 아직 미표시(§10-3 후속 과제, 백엔드는 정상).
- **Phase B 숏 연구(기존 6알고)는 2026-08-15에 종결됐다.** 1순환(macd_momentum·omnibus·
  regime_trend·multi_factor·vix_rsi·fng_contrarian 6개 알고 거울반전) + 2순환
  (GJR-GARCH 레버리지효과 진단·macd_momentum 모멘텀 vol 사이징) 전부 기각.
  같은 사양은 물론, 이미 반증된 축(가격변동성 비대칭·모멘텀 고유 변동성
  사이징)의 재탐색도 하지 마 — 새로운 근거·데이터 없이는 이 방향을 다시
  열지 마. 상세: docs/arena/research/spot-to-perp-phase-b-short-entry-design-20260815.md
  §8~§17, docs/arena/overview/decision-log.md D017.
- 선물 트랙은 무기한 롱온리로 확정됐다. `vix_rsi`(ETH)만 DSR 0.934(기준 0.95)로
  근접 미달인 별개 트랙 — 표본이 더 쌓일 때까지 그리드 재탐색 없이 관찰만 지속.
- 운영 DB는 최적화 후 약 206 MiB이며 500 MiB 한도에서 불필요한 복제·인덱스·대형
  JSON을 피해야 한다.

작업 방식:
1. git 상태와 최근 관련 커밋을 확인하고 사용자 변경을 보존해.
2. 코드, 테스트, migration을 기준으로 handoff 서술이 현재와 일치하는지 확인해.
3. Supabase MCP와 AWS SSM이 연결돼 있으면 운영 상태를 읽기 전용으로 먼저 확인해.
4. Phase B는 종결됐으니 다시 열지 말고, 운영·인프라 작업이나 §10의 다른 로드맵
   항목(P5/P6 등) 중 가치가 가장 높은 안전한 작업을 설계해 진행해.
5. 다음 변경이 필요하면 spot/perp 공통 데이터는 재사용하고, 포지션·리스크·방향처럼
   의미가 다른 것만 트랙별로 분리해.
6. 변경 후 가장 좁은 테스트와 Ruff를 먼저 실행하고 영향이 넓으면
   env PYTHONPATH=.:src UV_CACHE_DIR=.cache/uv uv run pytest tests/test_arena_*.py -q까지 실행해.
7. 운영 변경을 적용했다면 서비스 active 상태, 재시작 횟수, 최근 오류 로그, 신규
   spot/perp 실행과 DB 용량을 확인해.

경계:
- .env*나 자격증명 값을 읽거나 출력하지 마.
- 현물 트랙레코드를 초기화하거나 검증되지 않은 숏을 활성화하지 마.
- Phase B(숏 진입 로직)를 새 근거 없이 재탐색하지 마 — 종결된 스레드다.
- gw/, lambda/arena/, review/, terraform/의 별도 작업은 건드리지 마.
- 운영에 이미 적용된 내용을 다시 적용하기 전에 migration 이력을 확인해.

결과는 결론부터 보고하고, 확인한 운영 수치, 변경 파일, 테스트 결과, 남은 위험과
다음 한 가지 행동을 명확히 정리해줘.
```

## 10. 다음 우선순위

**Phase B 숏 연구(기존 6알고)는 2026-08-15에 종결됐다**(1순환 §14 + 2순환 §17
종합). 6개 알고 거울반전, GJR-GARCH 진단, 모멘텀 고유 변동성 사이징까지 전부
§4 채택 기준(DSR≥0.95, CI 하한>0, 전/후반 부호일관)을 충족하지 못해 이 6알고
기준 `PERP_SHORT_ENABLED_TRACKS`는 빈 집합을 유지하며, 이 6알고의 선물 트랙은
무기한 롱온리로 확정됐다(신규 `meridian`은 D019 별개 경로로 이미 숏 등록 —
위 §1 참조, 이 결론과 모순 아님). 남은 선택지는 다음 두 가지뿐이다(우선순위
아님, 개별 판단):

1. `vix_rsi`(ETH, veto유지, DSR 0.934)만 근접 미달이라 표본이 더 쌓일 때까지
   관찰(그리드 재탐색 없이 대기)한 뒤 재평가한다.
2. §13에서 발견한 `backtest.py`의 fng 전용 이익포착/물타기 로직이 `position.direction`을
   보지 않는 결함을 (현재 도달 불가능한 경로라도) 정합성 차원에서 정식 수정할지
   별도로 결정한다.

Phase B 자체를 다시 여는 것(새 알고 거울반전 재시도, 레버리지효과·모멘텀사이징
축 재탐색 등)은 새로운 근거·데이터 없이는 하지 않는다.

**meridian 후속 작업(2026-08-15 추가)**:

3. **대시보드 미표시 — 후속 필요**: `arena/index.html`의 `ALGOS`/`ALGO_IDS`에
   `meridian`을 아직 추가하지 않았다. `computeGrandTotal()`이 `ALGO_IDS`를
   모든 자산×시장에 균일 적용하는 구조라, 그대로 추가하면 존재하지 않는 spot
   슬롯 3개(빈 슬롯 $1,000×0%)가 총수익률 계산에 섞여 2026-08-15 오전 세션에서
   고친 것과 같은 "빈 슬롯 희석" 버그가 재발한다. `meridian`이 perp 전용이라는
   사실을 프론트엔드도 인식하도록(예: `ALGOS`에 `scope: 'perp'` 필드 추가 후
   `computeGrandTotal`/탭 렌더가 이를 반영) 고쳐야 하며, 반드시 브라우저에서
   실제 렌더 확인 후 배포한다. 백엔드는 이미 정상 거래·기록 중이라 이 작업은
   급하지 않다(데이터 유실 없음, 표시만 안 될 뿐).
4. `meridian` 라이브 관찰 — 표본이 쌓이면(예: 20~50건) 롱/숏 leg별 성과를
   분해해 볼 가치가 있다(설계 문서 §5 미결정 사항 참고, 예: 숏 사이징 감쇠값
   재조정 여부). 지금은 관찰만, 그리드 튜닝 시작하지 않는다.

다음 세션 리소스는 위 3(대시보드)·4(관찰) 또는 CLAUDE.md 로드맵의 다른 항목
(P5 청산데이터·P6 숏/스테이블 슬리브 등 사용자 결정 대기 항목)이나 운영·인프라
작업으로 재배치하는 게 합리적이다.
