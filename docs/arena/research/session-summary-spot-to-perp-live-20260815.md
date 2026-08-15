# 세션 요약 — Vanguard 스프린트 → Spot→Perp 트랙 분리 → 선물 실거래 활성화 (2026-08-15)

이 문서는 2026-08-15 세션 전체(스프린트 방법론 전환부터 선물 실거래 활성화·배포까지)를
시간순으로 묶은 인덱스다. 각 항목의 상세 설계·검증 수치는 링크된 개별 문서 참조.
CLAUDE.md는 `.gitignore`에 있어(로컬 전용) git 이력에 안 남으므로, 이 문서가 실질적인
커밋된 기록이다.

## 1. 방법론 전환 — "무기한 대기"에서 "스프린트"로

사용자가 "정직한 표본 확보"라는 기존 원칙이 "조금 고치고 실거래 표본 쌓일 때까지
무기한 대기"로 굳어지는 건 방향이 아니라고 지적. 재확인 결과 P1~P8·D1~D5 등 지금까지
개선 작업 대부분이 실제로는 이미 "가설→백테스트→당일 결론" 스프린트 구조였다는 게
드러남(재시도 금지 목록 자체가 증거) — 문제는 최근 국면이 "대기"로 프레이밍되면서
루프가 멈춘 것. **구분 원칙**: 캘린더에 실제로 묶인 것(라이브 검증, 승격 판단)은
배경 큐에 두고, 백테스트로 당장 검증 가능한 나머지는 스프린트로 돌린다.

**첫 스프린트 — 자산간 상대강도 후보 "Vanguard"**:
[relative-strength-candidate-vanguard-20260815.md](relative-strength-candidate-vanguard-20260815.md).
macro 미주입(순수 가격신호)으로 `arena_ohlcv_bars` 전체 커버리지를 써서 표본
n=125~251/자산을 당일에 확보하는 방법론 자체는 검증됐으나, 이 특정 사양(BTC DSR
0.416·ETH CI전부음수·SOL DSR 0.710)은 채택선 미달로 **기각**.

## 2. "spot만으로는 한계" — 선물 전환 결정

사용자: "spot만으로는 한계가 명확하다 — future로 전환해서 롱/숏 모두 대응 가능하게."
Binance 공식 문서 기준 루브릭 검증(REST/WS 엔드포인트 전부 대조 — 결과: 전부 정확,
특히 WI-9 청산스트림 `/market` 라우팅 수정이 Binance의 2026-04-23 WS 마이그레이션
공지와 정확히 일치함을 재확인) 이후 진행.

### Phase A — 인프라 (알고별 스위치 모델)
[spot-to-perp-phase-a-infrastructure-20260815.md](spot-to-perp-phase-a-infrastructure-20260815.md).
`perp_policy.py`(spot_policy 대칭 롱/숏 상태머신), 라이브 펀딩 정산, 알고별
`PERP_LIVE_ENABLED_ALGOS` opt-in. 구현 중 `backtest.py`의 fng_contrarian 물타기가
비-spot 분기에 없던 패리티 버그 발견·수정.

### Phase A2 — 자산×시장 루트 트랙 분리 (모델 변경)
사용자가 "기존 현물 트랙레코드는 초기화 안 함, 현물/선물을 자산(BTC/ETH/SOL)과 동일
레벨의 독립 루트 트랙으로 분리"로 방향을 재확정 — Phase A의 알고별 스위치 모델을
대체. [spot-to-perp-phase-a2-root-track-split-20260815.md](spot-to-perp-phase-a2-root-track-split-20260815.md).
핵심: `symbol="{실제티커}-PERP"` 컨벤션으로 기존 멀티에셋 파티셔닝(state.py/DB
유니크인덱스/대시보드)을 마이그레이션 없이 재사용. 로컬 검증 중 실제 경합조건(빠른
탭 전환 시 stale 응답이 최신 데이터를 덮어씀) 발견·수정.

## 3. 배포 — SSH 차단, AWS SSM으로 우회

세션 진행 중이던 EC2 코드 갱신 표준 절차(`ssh -i ~/.ssh/arena_ed25519 ubuntu@3.39.201.112`,
`docs/arena/operations/access-runbook.md`에 문서화된 방식)가 **이 세션 환경에서
포트 22 아웃바운드가 막혀 있어 작동하지 않음**(일반 HTTPS는 정상 — GitHub·Binance·
Cloudflare 전부 200 응답, `ssh`/`nc` 둘 다 포트 22에서만 타임아웃). 사용자가 "여기
문서화되어 있을 것"이라고 지목한 `terraform/modules/iam/main.tf`에 이미 **SSM Session
Manager**(포트 22 불필요) 인프라가 준비돼 있었음을 발견 — `terraform/outputs.tf`의
`ssm_connect` output이 그 존재를 확인해줌.

**실제 사용한 배포 경로**(신규 문서화 — 상세는
[ssm-deploy-fallback-20260815.md](../operations/ssm-deploy-fallback-20260815.md)):
`aws ssm send-command`(AWS-RunShellScript)로 파일을 gzip+base64 인코딩해 원격에
쓰고, `compileall` + `systemctl restart`. `session-manager-plugin`(대화형 SSH-오버-SSM
터널에 필요한 도구)은 설치 시 sudo 비밀번호가 필요해 이 비대화형 환경에서 설치
불가 — 대신 `send-command`/`get-command-invocation`만으로 비대화형 배포를 완성.

**배포 순서**: 커밋(`8158057`) → Cloudflare Pages 대시보드 배포(확인: `arena.sovereignwon.com`
에 새 마켓 토글 렌더됨) → SSM으로 `src/arena/` 11개 파일 배포 → `arena.service` 재시작 →
로그로 정상 사이클 실행 확인(에러 0건).

## 4. 선물 실거래 활성화

사용자: "선물 거래도 켜놔." `ARENA_PERP_LIVE_ENABLED` False→True(커밋 `73e020a`,
push 완료), `PERP_LIVE_ENABLED_ALGOS`는 여전히 빈 집합 유지(숏은 미승인 — Phase B
없이는 안 됨, 선물 트랙도 현물과 동일 롱온리 신호로만 진입, 차이는 펀딩비뿐).
동일 SSM 경로로 `parameters.py` 재배포·재시작.

**재시작 즉시 결과** (실제 라이브, 2026-08-15 08:46 UTC):

| 트랙 | 알고 | 방향 | 진입가 |
|---|---|---|---|
| BTCUSDT-PERP | fng_contrarian, vix_rsi | long | $63,075.43 |
| ETHUSDT-PERP | macd_momentum | long | $1,880.40 |
| SOLUSDT-PERP | fng_contrarian, macd_momentum, vix_rsi | long | $75.24 |

현물과 동일 신호라 방향·진입가가 겹침(예상된 동작). 총 18슬롯(3자산×6알고) 신규
가동, 6건 즉시 진입. 재시작 순간 6개 사이클(BTC현물+ETH/SOL섀도우+3개 선물)이
동시에 몰리며 Binance futures `basis` API가 일시 `418`(레이트리밋) 응답했으나
그레이스풀 처리(연구용 부가지표, 트레이딩 결정 무관)로 다음 사이클에 정상
복구됨 — 정규 4H cron은 심볼별 스태거링돼 있어 재발 가능성 낮음.

## 5. 커밋 이력 (이 세션)

```
73e020a feat(arena): ARENA_PERP_LIVE_ENABLED 활성화 — BTC/ETH/SOL 선물 트랙 실거래 시작
8158057 feat(arena): spot→perp 트랙 분리 인프라 + 실행게이트 재보정 + 신규 알고 후보 스프린트
```
둘 다 `origin/main`에 push 완료.

## 6. 미해결·후속 과제

- 대시보드 로컬 프리뷰의 원인 불명 콘솔 500 에러(기능 영향 없음, [Phase A2 문서](spot-to-perp-phase-a2-root-track-split-20260815.md) §미해결 참조) — 실제 배포 환경 재현 여부 미확인.
- Phase B(알고별 숏 진입 로직 설계·백테스트) — 제안 순서: macd_momentum(TSMOM_NL 이미 연속신호)→omnibus DOWN_TREND→regime_trend→multi_factor→vix_rsi/fng_contrarian.
- 전용 perp 가격 피드(현재 spot 프록시 유지) — 별도 스프린트.
- `session-manager-plugin` sudo 설치 불가 문제 — 대화형 포트포워딩(rsync 등 파일 도구 재사용)이 필요해지면 별도 방법(예: 사용자가 직접 설치) 필요. `send-command` 방식은 파일 단위 배포만 가능, 대화형 셸·양방향 스트리밍은 불가.
