# ETH/SOL 대시보드 보조 뉴스 — 설계·구현 (2026-08-03)

## 배경 및 스코프 결정

morning-brief가 2026-07-31에 newsdata.io(`coin=BTC,ETH,SOL`)를 연동하면서 뉴스 수집
범위가 넓어졌는데, 이게 "아레나 멀티자산 파이프라인"으로 배선된 것인지 질문이 나왔다.
확인 결과: **아니다** — CoinDesk API가 죽어서 대체 소스를 찾다가 우연히 ETH/SOL도
잡히게 된 것뿐이고, morning-brief는 여전히 BTC 단일 브리핑이며 `join.py`도 BTC 전용
그대로다.

사용자에게 "그럼 진짜 멀티자산 파이프라인으로 배선할까?"를 물었더니, 이건
`multi-asset-implementation-plan-20260731.md`가 이미 취소한 **Phase 2**(자산고유
피처를 트레이딩 신호 입력으로 쓰는 것)와 겹치는 질문이었다 — D-verdict(6알고 전부
크로스에셋 실패) 때문에 취소된 항목. 스코프를 좁혀 확인한 결과:

**채택된 스코프: 아레나 ETH/SOL 대시보드 보조.** 방금 만든 shadow 카드/로그 옆에
관련 뉴스 헤드라인을 보여주는 것 — 트레이딩 로직에는 전혀 연결하지 않는다. 이건
"자산고유 데이터를 알고리즘 입력으로 쓸 가치가 있는가"라는, D-verdict가 이미 답한
질문과 다르다(순수 정보 표시 vs 신호 입력). 그래서 D-verdict·Phase 2 취소와 무관하게
진행 가능하다고 판단했다.

**기각한 대안**: (1) 독립적인 ETH/SOL 모닝브리프 콘텐츠 제품 — `join.py` 전체를
자산별로 인스턴스화해야 하는 큰 작업, LLM/API 비용 3배, 이번 요청 범위 밖. (2) 뉴스
감성을 자산고유 피처로 만들어 알고 게이트에 연결 — 정확히 취소된 Phase 2 재개.

## 아키텍처

morning_brief 패키지와 완전히 분리된 별도 구현(아레나는 morning_brief를 import하지
않는 기존 관례 유지):

```
src/arena/asset_news.py (신규)
  └─ fetch_asset_news(api_key, coins="ETH,SOL", ...) — newsdata.io /1/crypto 단발 호출
       coin 필드 → symbol 매핑(ARENA_ASSET_NEWS_COIN_SYMBOL_MAP), 자산별 행 중복 생성
       API 키 없음/HTTP 실패/응답 오류 → 전부 빈 리스트 반환(사이클 안 죽음)

src/arena/data_lake.py
  └─ record_asset_news_items() — arena_asset_news upsert(on_conflict=symbol,url)
       _safe_execute_optional_schema 재사용 — 테이블 마이그레이션 전에도 안전

src/arena/scheduler.py
  └─ _run_asset_news_cycle_safe() — 1일 1회 cron(03:30 UTC, ENABLE_ARENA_ASSET_NEWS 게이트)
       4H 사이클과 무관 — 뉴스는 그렇게 자주 안 바뀜 + 무료 크레딧(200/일) 보존

arena_asset_news (Supabase, 신규 테이블)
  └─ symbol, title, url, source, published_at, summary
  └─ RLS: anon SELECT 정책(arena_shadow_decisions와 동일 패턴, 이 세션에서 이미
       arena_runs/arena_shadow_decisions에 적용한 것과 동일하게 처음부터 포함)

arena/index.html
  └─ RELATED NEWS 패널 — ETH/SOL 탭에서만 표시(가격차트와 SHADOW SIGNAL LOG 사이)
       fetchAssetNews() → renderAssetNews(), switchAsset()에서 shadow 데이터와 병렬 fetch
```

## 비용/운영

- newsdata.io 무료 플랜 200크레딧/일, 요청당 1크레딧. morning-brief가 이미 1회/일
  쓰고 있고, 이 기능은 별도로 1회/일 추가 — 합계 2/일, 한도 대비 여유 큼.
- **`NEWSIO_API_KEY`가 EC2 `.env`에 아직 없음** — GitHub Actions secret으로만
  존재(morning-brief 전용). 아레나에서 쓰려면 EC2에 같은 키를 추가해야 함.
- `ENABLE_ARENA_ASSET_NEWS`는 기본 `false`. 키가 없어도 `fetch_asset_news()`가
  빈 리스트를 반환해 안전하지만, 플래그 자체도 켜야 cron job이 등록됨.

## 구현 상태 (2026-08-03)

- ✅ 코드 구현 완료: `asset_news.py`, `data_lake.py`, `scheduler.py`, `config.py`,
  `parameters.py` — 전부 기본 off, BTC 라이브 경로 무접촉.
- ✅ 테스트: `tests/test_arena_asset_news.py`(8건, coin 매핑/cutoff 필터/graceful
  degradation), 기존 arena 158개 테스트 전체 통과, ruff/mypy 회귀 없음.
- ✅ 마이그레이션 적용 완료(Supabase MCP): `arena_asset_news` 테이블 + anon RLS 정책.
- ✅ EC2 배포 완료(코드 반영, 서비스 재시작 정상) — 단 플래그 off라 실제로는
  아무 것도 안 함(설계대로).
- ✅ 대시보드(`arena/index.html`) 구현·배포 완료 — playwright로 BTC/ETH/SOL 왕복,
  콘솔 에러 0건, "아직 수집된 관련 뉴스 없음" graceful 빈 상태 확인.
- ⬜ **미완료(사용자 액션 필요)**: EC2 `.env`에 `NEWSIO_API_KEY` 추가 +
  `ENABLE_ARENA_ASSET_NEWS=true` 설정 후 서비스 재시작 — 이 두 가지가 되어야
  실제 뉴스가 채워지기 시작함.

## 재현/확인

```bash
# 로컬 테스트
.venv/bin/python3 -m pytest tests/test_arena_asset_news.py -q

# 활성화(EC2, 사용자가 직접 또는 요청 시 수행)
ssh -i ~/.ssh/arena_ed25519 ubuntu@3.39.201.112 \
  'echo "NEWSIO_API_KEY=<값>" >> /home/ubuntu/news/.env && \
   echo "ENABLE_ARENA_ASSET_NEWS=true" >> /home/ubuntu/news/.env && \
   sudo systemctl restart arena.service'
```
