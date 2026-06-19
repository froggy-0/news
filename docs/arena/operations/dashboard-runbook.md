# Arena 대시보드 Runbook

> 작성일: 2026-06-20  
> 대상: `arena.sovereignwon.com` Cloudflare Pages 대시보드

---

## 개요

| 항목 | 값 |
|---|---|
| URL | https://arena.sovereignwon.com |
| CF Pages 프로젝트 | `arena` |
| 코드 | `arena/index.html` (단일 파일 CSR) |
| 배포 방식 | Wrangler CLI → Cloudflare Pages |
| 데이터 소스 | Supabase `paper_positions` (anon key) |

---

## 대시보드 구성

### 화면 구성
1. **상단 헤더** — BTCUSDT 현재가 + 24H 등락 (60초 폴링)
2. **알고리즘 카드** (5개) — 총 수익률, 포지션 상태, 미실현 손익
3. **Equity Curve 차트** — 알고리즘별 누적 수익률 라인 (Chart.js)
4. **Trade Log** — 모든 거래 내역 (open/closed), 최신순

### 상태 처리
- **거래 없음**: `—` + "AWAITING FIRST TRADE CLOSE" placeholder
- **open만 있음**: BTC 현재가 기준 미실현 손익 % 표시 (`unrlzd`)
- **closed 있음**: 실현 수익률 + equity curve

### 실시간 업데이트
- Supabase Realtime WebSocket (`postgres_changes`) → 거래 발생 즉시 갱신
- BTC 가격: Binance `/api/v3/ticker/24hr` 60초 폴링 → 미실현 손익 갱신

---

## 배포

```bash
cd /Users/giwon/code/news

# 단일 파일 수정 후 바로 배포
npx wrangler pages deploy arena/ --project-name arena --commit-dirty=true
```

배포 성공 시 `*.arena-ewr.pages.dev` 프리뷰 URL 출력.

---

## 커스텀 도메인 관련

- DNS: `arena.sovereignwon.com` CNAME → Cloudflare (오렌지 클라우드)
- CF Pages 커스텀 도메인: **wrangler 4.x `pages domain add` 미지원**
  → Cloudflare Dashboard → Workers & Pages → arena → Custom domains에서 수동 추가
- 도메인 추가 후 SSL 발급까지 2~3분 소요

---

## Supabase 설정 요구사항

대시보드는 anon key(publishable)를 사용하므로 RLS 필요:

```sql
-- paper_positions 공개 읽기 허용 (이미 적용됨)
CREATE POLICY "public_read" ON paper_positions
  FOR SELECT USING (true);

-- Realtime 활성화 (Supabase 대시보드 → Database → Replication → paper_positions 체크)
```

---

## 로컬 개발

```bash
cd /Users/giwon/code/news
python3 -m http.server 8791 --directory arena
# → http://localhost:8791
```

`.claude/launch.json`에 등록됨 (프리뷰 서버 자동 실행).

---

## 주요 JS 구조 (arena/index.html)

```
fetchPositions()     — Supabase SELECT (최신 500건)
algoStats(ps)        — 알고리즘별 통계 계산 + 미실현 손익
renderCards(stats)   — 카드 렌더링
equityCurves(ps)     — 날짜별 누적 수익률 계산
renderChart(curves)  — Chart.js 라인차트
renderLog(ps)        — 거래 로그 테이블
fetchBtcPrice()      — Binance 가격 + 카드 미실현 손익 갱신
```

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| 모든 값 `—` 또는 0% | closed 거래 없음 (정상) | 첫 청산 후 자동 반영 |
| 522 Error | CF Pages 커스텀 도메인 미등록 | CF 대시보드에서 도메인 추가 |
| 데이터 안 보임 | Supabase RLS 없음 | public_read 정책 생성 |
| Realtime 미작동 | Supabase Replication 비활성 | 대시보드 → Replication 체크 |
