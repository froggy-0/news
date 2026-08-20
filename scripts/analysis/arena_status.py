"""arena-status: 실행시점 아레나 거래 현황 + 히스토리 분석 (지속적 알고 개선용).

한 번의 실행에서 asyncio.gather로 병렬 조회 → 압축 요약 출력. 스키마·컬럼은 스킬
(.claude/skills/arena-status/SKILL.md)에 문서화돼 있어 재탐색 불필요.

멀티트랙(2026-08-20): 자산 3종(BTC/ETH/SOL) × 시장 2종(현물/선물) = 6개 독립 트랙 전부를
분석한다. 이전 버전은 `symbol='BTCUSDT'` 하드필터라 2026-08-06 ETH/SOL 실거래 승격과
2026-08-15 perp 트랙 이후 자본의 2/3가 화면 밖이었고, 알고 순위가 실제와 뒤바뀌어 보였다
(예: vix_rsi가 BTC현물 -4.68%였으나 전 트랙 실제는 +1.51%).

섹션:
  0) 트랙 요약 — 자산×시장 매트릭스 (어느 트랙이 벌고 잃나)
  1) 오픈 포지션 + 실시간 미실현손익 (방향 보정, 델타중립 페어 순노출 표시)
  2) 알고 × 트랙 가중합 교차표 (알고가 어느 트랙에서 지고 있나)
  3) 청산 거래 알고별 성과 — 표준지표(expectancy·profit factor·payoff·노출률)
  4) params_version 분리 + 현재 버전 이후만
  5) MFE/MAE 청산 품질 (숏은 방향 반전 적용)
  6) 현재 macro/레짐 스냅샷 (진입 게이트 컨텍스트)
  7) 진입조건→결과 분석 (레짐별·macd_hist부호별·close_reason별)
  8) 라이브 차단 사유 (arena_decisions — 트랙별로 무엇이 진입을 막나)

옵션:
  --track <sym>    : 특정 트랙만 (예: BTCUSDT-PERP). 반복 지정 가능.
  --market spot|perp : 시장 축 필터.
  --algo <id>      : 특정 알고만 상세(섹션 7·8).
  --days <n>       : 차단 사유 집계 기간(기본 14일).
  --since-version  : 섹션4 "현재 버전 이후만" 기준(기본: parameters.PARAMS_VERSION).
  --fresh-backtest : macro 백필 백테스트 즉석 재계산(~30-60s, BTC 현물 기준).

재현: .venv/bin/python3 scripts/analysis/arena_status.py
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arena import algorithms, parameters, positions  # noqa: E402

# 라이브 알고 전체(8종) — 하드코딩 대신 ALGORITHMS에서 유도해 신규 알고 추가 시 자동 반영.
ALGOS: list[str] = list(algorithms.ALGORITHMS)

# 자산 × 시장 = 6트랙. 트랙 심볼 컨벤션의 유일한 생성 지점은 parameters.perp_track_symbol.
SPOT_TRACKS: list[str] = list(parameters.MULTI_ASSET_SYMBOLS)
PERP_TRACKS: list[str] = [parameters.perp_track_symbol(s) for s in parameters.MULTI_ASSET_SYMBOLS]
TRACKS: list[str] = [
    t for s in parameters.MULTI_ASSET_SYMBOLS for t in (s, parameters.perp_track_symbol(s))
]

PRICE_URL = "https://api.binance.com/api/v3/ticker/price"


def _is_perp(symbol: str) -> bool:
    return symbol.endswith(parameters.PERP_TRACK_SUFFIX)


def _track_label(symbol: str) -> str:
    """'BTCUSDT-PERP' → 'BTC 선물' / 'BTCUSDT' → 'BTC 현물'."""
    base = parameters.real_ticker_for_track(symbol).replace("USDT", "")
    return f"{base} {'선물' if _is_perp(symbol) else '현물'}"


def _algo_in_track(algo: str, symbol: str) -> bool:
    """parameters.ALGORITHM_TRACK_SCOPE 기준으로 그 알고가 이 트랙에서 도는가."""
    scope = parameters.ALGORITHM_TRACK_SCOPE.get(algo)
    return True if scope is None else symbol in scope


def _version_num(v: str | None) -> int:
    """'arena-params-v30' → 30. 파싱 불가 시 -1(항상 필터 밖)."""
    if not v:
        return -1
    try:
        return int(v.rsplit("v", 1)[-1])
    except ValueError:
        return -1


def _dt(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d
    except ValueError:
        return None


def _age_h(ts: str | None, now: datetime) -> float | None:
    d = _dt(ts)
    return (now - d).total_seconds() / 3600.0 if d else None


def _sign(direction: str | None) -> int:
    """long=+1 / short=-1. perp 트랙 숏 손익·MFE 방향 보정용."""
    return -1 if (direction or "long") == "short" else 1


def _fmt_px(v: float | None) -> str:
    """자산별 가격 스케일 차이(BTC 6.9e4 ~ SOL 85) 대응 — 지수표기 방지."""
    if v is None:
        return "?"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    return f"{v:.2f}" if abs(v) >= 1 else f"{v:.4f}"


async def _prices() -> dict[str, float]:
    """실제 바이낸스 티커별 현재가. perp 트랙도 spot 가격 프록시를 쓴다(라이브와 동일)."""
    symbols = ",".join(f'"{s}"' for s in parameters.MULTI_ASSET_SYMBOLS)
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(PRICE_URL, params={"symbols": f"[{symbols}]"})
            r.raise_for_status()
            return {row["symbol"]: float(row["price"]) for row in r.json()}
    except Exception:
        return {}


async def _open_positions() -> list[dict]:
    res = (
        await positions.db()
        .table("paper_positions")
        .select(
            "id,algo_id,direction,open_time,open_price,stop_loss_price,position_weight,"
            "trail_distance,signal_reason,params_version,symbol"
        )
        .eq("status", "open")
        .order("open_time")
        .execute()
    )
    return res.data or []


async def _closed_trades() -> list[dict]:
    res = (
        await positions.db()
        .table("paper_positions")
        .select(
            "algo_id,direction,open_time,close_time,open_price,close_price,ret_pct,"
            "position_weight,hold_hours,close_reason,params_version,macro_snapshot,signal_reason,symbol"
        )
        .eq("status", "closed")
        .not_.is_("ret_pct", "null")
        .order("close_time")
        .limit(5000)
        .execute()
    )
    return res.data or []


async def _latest_macro() -> dict | None:
    res = (
        await positions.db()
        .table("arena_macro_snapshots")
        .select("fetched_at,reference_date,stale_hours,risk_overlay")
        .order("fetched_at", desc=True)
        .limit(1)
        .execute()
    )
    return (res.data or [None])[0]


async def _decisions(days: int) -> list[dict]:
    """arena_decisions — 사이클마다 알고별 행동·차단사유 로그(라이브 near-miss).

    arena_decisions 자체엔 symbol 컬럼이 없음(run_id,algo_id로만 upsert). 6개 트랙이
    각자 별도 run_id로 사이클을 돌므로 arena_runs(run_id→symbol)로 심볼을 붙여야
    트랙별 집계가 가능하다(안 붙이면 6트랙 결정이 뭉개져 집계됨).
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    runs = (
        await positions.db()
        .table("arena_runs")
        .select("run_id,symbol")
        .gte("started_at", since)
        .limit(20000)
        .execute()
    )
    sym_by_run = {r["run_id"]: r["symbol"] for r in (runs.data or [])}
    if not sym_by_run:
        return []
    out: list[dict] = []
    run_ids = list(sym_by_run)
    # in_() URL 길이 제한 회피 — 청크 분할 조회
    for i in range(0, len(run_ids), 200):
        chunk = run_ids[i : i + 200]
        res = (
            await positions.db()
            .table("arena_decisions")
            .select("algo_id,action,skipped_reason,created_at,run_id")
            .in_("run_id", chunk)
            .limit(20000)
            .execute()
        )
        for d in res.data or []:
            d["symbol"] = sym_by_run.get(d["run_id"])
            out.append(d)
    return out


async def _bars(ticker: str, start_iso: str) -> tuple[str, list[dict]]:
    """MFE/MAE·벤치마크용 4h 봉. arena_ohlcv_bars는 spot 티커만 보유 —
    perp 트랙은 real_ticker_for_track()으로 같은 봉을 공유한다(라이브도 spot 가격 프록시)."""
    res = (
        await positions.db()
        .table("arena_ohlcv_bars")
        .select("open_time,high,low,close")
        .eq("symbol", ticker)
        .eq("interval", "4h")
        .gte("open_time", start_iso)
        .order("open_time")
        .limit(6000)
        .execute()
    )
    seen: dict[str, dict] = {}
    for r in res.data or []:
        seen[r["open_time"]] = r  # 중복 봉(run별 기록) 마지막 값으로 dedup
    return ticker, sorted(seen.values(), key=lambda r: r["open_time"])


def _agg(trades: list[dict], key: str = "ret_pct") -> dict:
    n = len(trades)
    if n == 0:
        return {
            "n": 0, "win": 0.0, "sum_w": 0.0, "avg": 0.0, "hold": 0.0,
            "expectancy": 0.0, "pf": 0.0, "payoff": 0.0,
        }  # fmt: skip
    rets = [(t.get(key) or 0.0) for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    sum_w = sum((t.get(key) or 0) * (t.get("position_weight") or 1.0) for t in trades) * 100
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    avg_win = statistics.mean(wins) if wins else 0.0
    avg_loss = abs(statistics.mean(losses)) if losses else 0.0
    holds = [t["hold_hours"] for t in trades if t.get("hold_hours") is not None]
    return {
        "n": n,
        "win": len(wins) / n * 100,
        "sum_w": sum_w,
        "avg": statistics.mean(rets) * 100,
        "hold": statistics.mean(holds) if holds else 0.0,
        # Expectancy(%/거래) = win%×평균승 − loss%×평균패 — 장기 생존성 1차 지표.
        "expectancy": (len(wins) / n * avg_win - len(losses) / n * avg_loss) * 100,
        # Profit Factor = 총이익/총손실. >1.5 지속가능, >2.0 강한 엣지.
        "pf": (gross_win / gross_loss) if gross_loss > 0 else float("inf") if gross_win else 0.0,
        # Payoff = 평균승/평균패. 승률과 함께 봐야 함.
        "payoff": (avg_win / avg_loss) if avg_loss > 0 else 0.0,
    }


def _mfe_mae(trade: dict, bars: list[dict]) -> tuple[float, float] | None:
    """보유기간 4h봉 high/low 기준 MFE/MAE(소수). 봉 없으면 None.

    숏은 방향 반전 — 유리한 이동은 저가(low), 불리한 이동은 고가(high)다.
    4h 봉 단위라 인트라바 극값은 과소평가될 수 있음(보수적 추정).
    """
    ot, ct = _dt(trade.get("open_time")), _dt(trade.get("close_time"))
    op = trade.get("open_price") or 0.0
    if not ot or not ct or op <= 0:
        return None
    hi, lo = None, None
    for b in bars:
        bt = _dt(b["open_time"])
        if bt is None or bt < ot - timedelta(hours=4) or bt > ct:
            continue
        h, low_ = float(b["high"]), float(b["low"])
        hi = h if hi is None else max(hi, h)
        lo = low_ if lo is None else min(lo, low_)
    if hi is None or lo is None:
        return None
    if _sign(trade.get("direction")) < 0:
        return op / lo - 1.0, op / hi - 1.0  # short: 저가가 MFE, 고가가 MAE
    return hi / op - 1.0, lo / op - 1.0


def _latest_parquet() -> str:
    """data/sentiment_join/ 에서 가장 최근(mtime) master*.parquet 자동 선택."""
    d = Path(__file__).resolve().parents[2] / "data" / "sentiment_join"
    candidates = list(d.glob("master_*.parquet")) + list(d.glob("sentiment_join_master_*.parquet"))
    if not candidates:
        return "data/sentiment_join/sentiment_join_master_20260502.parquet"
    return str(max(candidates, key=lambda p: p.stat().st_mtime))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--algo", default="")
    ap.add_argument("--track", action="append", default=[], help="예: BTCUSDT-PERP (반복 가능)")
    ap.add_argument("--market", choices=["spot", "perp", "all"], default="all")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--fresh-backtest", action="store_true")
    ap.add_argument("--parquet", default=None, help="기본: 최신 master*.parquet 자동 선택")
    ap.add_argument(
        "--since-version",
        default=parameters.PARAMS_VERSION,
        help="섹션4 '현재 버전 이후만' 필터 기준(기본: 현재 PARAMS_VERSION)",
    )
    args = ap.parse_args()
    if args.parquet is None:
        args.parquet = _latest_parquet()
    if args.track:
        args.tracks = [t for t in TRACKS if t in set(args.track)]
        if not args.tracks:
            print(f"알 수 없는 트랙: {args.track} (가능: {', '.join(TRACKS)})")
            return 1
    elif args.market == "spot":
        args.tracks = SPOT_TRACKS
    elif args.market == "perp":
        args.tracks = PERP_TRACKS
    else:
        args.tracks = TRACKS
    return asyncio.run(_run(args))


async def _run(args) -> int:
    now = datetime.now(timezone.utc)
    await positions.init()
    prices, opens, closed, macro, decisions = await asyncio.gather(
        _prices(),
        _open_positions(),
        _closed_trades(),
        _latest_macro(),
        _decisions(args.days),
    )
    tracks: list[str] = args.tracks
    tset = set(tracks)
    opens = [p for p in opens if p.get("symbol") in tset]
    closed = [t for t in closed if t.get("symbol") in tset]

    # MFE/MAE·벤치마크용 봉 — 자산별로 첫 거래 시점부터 (perp는 spot 봉 공유)
    first_open = min((t["open_time"] for t in closed + opens if t.get("open_time")), default=None)
    tickers = sorted({parameters.real_ticker_for_track(t) for t in tracks})
    bars_by_ticker: dict[str, list[dict]] = {}
    if first_open:
        for tk, rows in await asyncio.gather(*(_bars(tk, first_open) for tk in tickers)):
            bars_by_ticker[tk] = rows

    def bars_for(symbol: str) -> list[dict]:
        return bars_by_ticker.get(parameters.real_ticker_for_track(symbol), [])

    def price_for(symbol: str) -> float | None:
        return prices.get(parameters.real_ticker_for_track(symbol))

    out: list[str] = []
    px = " ".join(f"{k.replace('USDT', '')}={v:g}" for k, v in sorted(prices.items()))
    out.append(f"# arena-status @ {now.strftime('%Y-%m-%d %H:%M UTC')}  {px}")
    out.append(
        f"트랙 {len(tracks)}개: {', '.join(_track_label(t) for t in tracks)}  |  ver={parameters.PARAMS_VERSION}"
    )

    by_track: dict[str, list[dict]] = defaultdict(list)
    by_algo: dict[str, list[dict]] = defaultdict(list)
    by_cell: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for t in closed:
        by_track[t["symbol"]].append(t)
        by_algo[t["algo_id"]].append(t)
        by_cell[(t["algo_id"], t["symbol"])].append(t)
    opens_by_track: dict[str, list[dict]] = defaultdict(list)
    for p in opens:
        opens_by_track[p["symbol"]].append(p)

    # 트랙별 개시 시점 — perp는 2026-08-15 승격이라 전 기간 기준으로 노출률·벤치마크를
    # 계산하면 현물과 비교 불가능해진다(선물이 부당하게 낮게/높게 보임).
    def track_start(tr: str) -> str | None:
        times = [
            t["open_time"]
            for t in by_track.get(tr, []) + opens_by_track.get(tr, [])
            if t.get("open_time")
        ]
        return min(times) if times else None

    # ── 0. 트랙 요약 ────────────────────────────────────────────
    out.append(f"\n## 0. 트랙 요약 (자산×시장) — 청산 {len(closed)}건 / 오픈 {len(opens)}건")
    out.append(
        "트랙 | 청산n | win% | 가중합% | 기대값%/T | PF | 노출%(알고평균) | 오픈 | buy&hold% | 개시일"
    )
    for tr in tracks:
        ts = by_track.get(tr, [])
        s = _agg(ts)
        pf = f"{s['pf']:.2f}" if s["pf"] != float("inf") else "inf"
        start = track_start(tr)
        span = max((_age_h(start, now) or 1.0), 1.0)
        # 알고별 독립 자본이라 단순 합산은 알고 수만큼 배가됨(>100%) — 스코프 내 알고 수로
        # 나눠 "알고 하나가 평균적으로 자본을 얼마나 굴렸나"로 정규화한다.
        n_scope = max(sum(1 for a in ALGOS if _algo_in_track(a, tr)), 1)
        expo = sum(t.get("hold_hours") or 0 for t in ts) / span / n_scope * 100
        # 벤치마크도 그 트랙 개시 이후 구간으로 — 전 기간 buy&hold와 섞으면 오독
        tb = [b for b in bars_for(tr) if start and b["open_time"] >= start]
        pr = price_for(tr)
        bh = f"{(pr / float(tb[0]['close']) - 1) * 100:+.2f}" if (tb and pr) else "?"
        out.append(
            f"{_track_label(tr)} | {s['n']} | {s['win']:.0f} | {s['sum_w']:+.2f} | "
            f"{s['expectancy']:+.2f} | {pf} | {expo:.0f} | {len(opens_by_track.get(tr, []))} | "
            f"{bh} | {str(start)[:10] if start else '-'}"
        )
    tot = _agg(closed)
    out.append(
        f"**전 트랙 합계** | {tot['n']} | {tot['win']:.0f} | {tot['sum_w']:+.2f} | "
        f"{tot['expectancy']:+.2f} | — | — | {len(opens)} | —"
    )
    spot_sum = _agg([t for t in closed if not _is_perp(t["symbol"])])
    perp_sum = _agg([t for t in closed if _is_perp(t["symbol"])])
    out.append(
        f"(현물 {spot_sum['n']}건 {spot_sum['sum_w']:+.2f}% / "
        f"선물 {perp_sum['n']}건 {perp_sum['sum_w']:+.2f}%)"
    )

    # ── 1. 오픈 포지션 ──────────────────────────────────────────
    out.append(f"\n## 1. 오픈 포지션 ({len(opens)})")
    if opens:
        out.append(
            "트랙 | algo | dir | 진입가 | 현재손익% | 보유h | 손절까지% | 목표가 | 비중 | ver"
        )
        net_by_algo_asset: dict[tuple[str, str], float] = defaultdict(float)
        for p in opens:
            op, sl = p["open_price"], p.get("stop_loss_price")
            sym = p["symbol"]
            pr = price_for(sym)
            sg = _sign(p.get("direction"))
            tgt = (p.get("signal_reason") or {}).get("omni_target_price")
            upnl = ((pr / op - 1) * 100 * sg) if (pr and op) else None
            # 손절까지 거리도 방향 보정(숏은 가격 상승이 손절 방향)
            to_stop = ((pr - sl) / pr * 100 * sg) if (pr and sl) else None
            hold = _age_h(p.get("open_time"), now)
            if upnl is not None:
                w = p.get("position_weight") or 1.0
                net_by_algo_asset[(p["algo_id"], parameters.real_ticker_for_track(sym))] += upnl * w
            out.append(
                f"{_track_label(sym)} | {p['algo_id']} | {p['direction']} | {_fmt_px(op)} | "
                f"{('%+.2f' % upnl) if upnl is not None else '?'} | "
                f"{hold:.0f} | {('%+.2f' % to_stop) if to_stop is not None else '?'} | "
                f"{_fmt_px(tgt) if tgt else '-'} | {p.get('position_weight') or 1:.2f} | "
                f"{p.get('params_version') or '?'}"
            )
        # 델타중립(현물롱+선물숏 동일 자산·동일 알고) 순노출 — 한쪽 다리만 보면 오해 소지
        pairs = [
            (a, tk, v)
            for (a, tk), v in sorted(net_by_algo_asset.items())
            if sum(
                1
                for p in opens
                if p["algo_id"] == a and parameters.real_ticker_for_track(p["symbol"]) == tk
            )
            > 1
        ]
        if pairs:
            out.append("※ 다리 2개 이상 보유(델타중립 가능) — 가중 순손익:")
            for a, tk, v in pairs:
                out.append(
                    f"   {a} / {tk}: 순 {v:+.3f}%p (개별 다리 손익은 상쇄됨 — 실손익은 펀딩·베이시스)"
                )
    else:
        out.append("(없음)")

    # ── 2. 알고 × 트랙 교차표 ───────────────────────────────────
    out.append("\n## 2. 알고 × 트랙 가중합% 교차표 (n | 가중합%)  ·=스코프 밖, -=거래 없음")
    hdr = (
        "algo".ljust(15)
        + " | "
        + " | ".join(_track_label(t).rjust(11) for t in tracks)
        + " |      합계"
    )
    out.append(hdr)
    for a in ALGOS:
        cells = []
        for tr in tracks:
            if not _algo_in_track(a, tr):
                cells.append("·".rjust(11))
                continue
            ts = by_cell.get((a, tr), [])
            cells.append(
                ("-".rjust(11)) if not ts else f"{len(ts)}|{_agg(ts)['sum_w']:+.2f}".rjust(11)
            )
        s = _agg(by_algo.get(a, []))
        cells.append(f"{s['n']}|{s['sum_w']:+.2f}".rjust(11))
        out.append(a.ljust(15) + " | " + " | ".join(cells))
    trow = []
    for tr in tracks:
        s = _agg(by_track.get(tr, []))
        trow.append(f"{s['n']}|{s['sum_w']:+.2f}".rjust(11))
    trow.append(f"{tot['n']}|{tot['sum_w']:+.2f}".rjust(11))
    out.append("합계".ljust(14) + " | " + " | ".join(trow))

    # ── 3. 알고별 표준지표 (전 트랙 통합) ────────────────────────
    out.append("\n## 3. 청산 거래 알고별 성과 (전 트랙 통합)")
    out.append("algo | n | win% | 가중합% | 기대값%/T | PF | payoff | 평균h | close_reason")
    for a in ALGOS:
        ts = by_algo.get(a, [])
        if not ts:
            continue
        s = _agg(ts)
        cr = dict(Counter(t.get("close_reason") for t in ts))
        pf = f"{s['pf']:.2f}" if s["pf"] != float("inf") else "inf"
        out.append(
            f"{a} | {s['n']} | {s['win']:.0f} | {s['sum_w']:+.2f} | {s['expectancy']:+.2f} | "
            f"{pf} | {s['payoff']:.2f} | {s['hold']:.0f} | {cr}"
        )

    # ── 4. params_version 분리 ──────────────────────────────────
    vers = sorted(
        {t.get("params_version") for t in closed if t.get("params_version")}, key=_version_num
    )
    if len(vers) > 1:
        out.append("\n### params_version별 (변경 효과)")
        for v in vers:
            vs = _agg([t for t in closed if t.get("params_version") == v])
            out.append(f"  {v}: n={vs['n']} win={vs['win']:.0f}% 가중합={vs['sum_w']:+.2f}%")
    since_num = _version_num(args.since_version)
    since_closed = [c for c in closed if _version_num(c.get("params_version")) >= since_num]
    if since_closed:
        out.append(f"\n### 현재 버전(`{args.since_version}`) 이후만 — 레거시 버전 손실 분리")
        out.append("algo | n | win% | 가중합% | 기대값%/T | PF")
        for a in ALGOS:
            ts = [c for c in since_closed if c["algo_id"] == a]
            if not ts:
                continue
            s = _agg(ts)
            pf = f"{s['pf']:.2f}" if s["pf"] != float("inf") else "inf"
            warn = " (표본 부족)" if s["n"] < 10 else ""
            out.append(
                f"{a} | {s['n']} | {s['win']:.0f} | {s['sum_w']:+.2f} | {s['expectancy']:+.2f} | {pf}{warn}"
            )
        legacy_closed = [c for c in closed if _version_num(c.get("params_version")) < since_num]
        if legacy_closed:
            out.append(
                f"(레거시 {len(legacy_closed)}건 누적 {_agg(legacy_closed)['sum_w']:+.2f}% vs 현행 "
                f"{len(since_closed)}건 {_agg(since_closed)['sum_w']:+.2f}% — "
                "누적 성과가 구버전에 지배되면 여기서 드러남)"
            )
        # 폐지된 청산경로 분리 — 현행 로직으로 도달 불가능한 손실이 누적치를 지배하는지
        dead = [
            c
            for c in closed
            if c["algo_id"] in parameters.PRICE_STOP_DISABLED_ALGOS
            and c.get("close_reason") in ("stop_loss", "trailing_stop")
        ]
        if dead:
            out.append(
                f"※ 가격손절 폐지 알고({', '.join(sorted(parameters.PRICE_STOP_DISABLED_ALGOS))})의 "
                f"stop_loss/trailing_stop {len(dead)}건 = {_agg(dead)['sum_w']:+.2f}% "
                "— 현행 로직으로는 도달 불가능한 경로(누적치 해석 시 제외 검토)"
            )

    # ── 5. MFE/MAE 청산 품질 ────────────────────────────────────
    out.append("\n## 5. MFE/MAE 청산 품질 (보유중 최대 유리/불리, 4h봉·숏 방향보정)")
    out.append("algo | n | 평균MFE% | 평균MAE% | MFE포착률% | MFE>1% 미실현 승리 | 해석힌트")
    for a in ALGOS:
        ts = by_algo.get(a, [])
        rows = []
        missed = 0
        for t in ts:
            mm = _mfe_mae(t, bars_for(t["symbol"]))
            if mm is None:
                continue
            mfe, mae = mm
            ret = t.get("ret_pct") or 0.0
            rows.append((mfe, mae, ret))
            if ret <= 0 and mfe >= 0.01:
                missed += 1  # 한때 +1% 이상이었는데 손실로 마감 — 청산 개선 신호
        if not rows:
            continue
        avg_mfe = statistics.mean(r[0] for r in rows) * 100
        avg_mae = statistics.mean(r[1] for r in rows) * 100
        caps = [r[2] / r[0] for r in rows if r[0] > 0.003]
        cap = statistics.mean(caps) * 100 if caps else 0.0
        hint = "청산이 이익 흘림(포착률<30%) → 목표가/트레일 검토" if cap < 30 else ""
        if avg_mae < -3 and any(r[2] > 0 for r in rows):
            hint += " | MAE 깊게 견딤 → 손절/사이징 검토"
        out.append(
            f"{a} | {len(rows)} | {avg_mfe:+.2f} | {avg_mae:+.2f} | {cap:.0f} | {missed} | {hint}"
        )

    # ── 6. 현재 macro/레짐 ──────────────────────────────────────
    out.append("\n## 6. 현재 macro/레짐")
    if macro:
        ro = macro.get("risk_overlay") or {}
        raw = ro.get("regimeRaw") or {}
        age = _age_h(macro.get("fetched_at"), now)
        out.append(
            f"레짐={ro.get('regimeState')} vol={ro.get('volLevel')}/{ro.get('volTrend')} "
            f"| FNG={raw.get('fng')} VIX={raw.get('vix_now')}(q40 {raw.get('vix_q40')}) "
            f"| breadth={raw.get('breadth_up_ratio')} stablecoin_z={raw.get('stablecoin_supply_zscore')} "
            f"| MA200상회={raw.get('btc_above_ma200')} 낙폭90d={raw.get('btc_drawdown_90d')} "
            f"| ref={macro.get('reference_date')} (fetched {age:.1f}h전)"
        )
        out.append("(macro는 시장 전체 지표 — 3자산 공유. 트랙별 레짐은 각 4h 봉으로 로컬 산출)")
    else:
        out.append("(macro 없음)")

    # ── 7. 진입조건→결과 분석 ───────────────────────────────────
    out.append("\n## 7. 진입조건→결과 분석 (알고 개선 신호, 전 트랙 통합)")
    algos_scope = [args.algo] if args.algo else ALGOS
    for a in algos_scope:
        ts = by_algo.get(a, [])
        if not ts:
            continue
        losers = [t for t in ts if (t.get("ret_pct") or 0) <= 0]

        def _in(t, path):
            sr = t.get("signal_reason") or {}
            return (sr.get("inputs") or {}).get(path)

        mh_neg = [t for t in ts if (_in(t, "macd_hist") or 0) < 0]
        mh_neg_win = (
            (sum(1 for t in mh_neg if (t.get("ret_pct") or 0) > 0) / len(mh_neg) * 100)
            if mh_neg
            else None
        )
        reg = Counter((t.get("macro_snapshot") or {}).get("arena_regime_state") for t in ts)
        dirs = Counter(t.get("direction") for t in ts)
        line = f"  [{a}] n={len(ts)} 손실={len(losers)} 방향{dict(dirs)}"
        if mh_neg_win is not None:
            line += f" | 진입시MACD음수 {len(mh_neg)}건 승률{mh_neg_win:.0f}%"
        line += f" | 진입레짐{dict(reg)} | 손실close_reason{dict(Counter(t.get('close_reason') for t in losers))}"
        out.append(line)
        # 트랙별 분해 — 특정 자산·시장에서만 지고 있는지 (BTC 단독 관측의 착시 방지)
        cells = [
            f"{_track_label(tr)} {len(by_cell[(a, tr)])}건 {_agg(by_cell[(a, tr)])['sum_w']:+.2f}%"
            for tr in tracks
            if by_cell.get((a, tr))
        ]
        if len(cells) > 1:
            out.append(f"      트랙별: {' / '.join(cells)}")

    # ── 8. 라이브 차단 사유 (트랙별) ─────────────────────────────
    out.append(f"\n## 8. 라이브 차단 사유 — 최근 {args.days}일 (트랙별로 무엇이 진입을 막나)")
    for tr in tracks:
        dec_by: dict[str, Counter] = defaultdict(Counter)
        act_by: dict[str, Counter] = defaultdict(Counter)
        for d in decisions:
            a = d.get("algo_id")
            if d.get("symbol") != tr or a not in ALGOS:
                continue
            if args.algo and a != args.algo:
                continue
            act_by[a][d.get("action")] += 1
            if d.get("action") in ("flat_skip", "risk_blocked") and d.get("skipped_reason"):
                dec_by[a][d["skipped_reason"]] += 1
        if not act_by:
            continue
        out.append(f"  ── {_track_label(tr)} ──")
        for a in sorted(act_by):
            opened = act_by[a].get("open", 0)
            top = ", ".join(f"{k} {v}" for k, v in dec_by[a].most_common(3))
            # 스코프 밖 알고의 잔여 로그(v39 이전 사이클 등) — 병목으로 오독 방지
            mark = "" if _algo_in_track(a, tr) else "  ⚠️스코프 밖(잔여 로그, 진입 불가)"
            out.append(f"    {a}: open={opened} {dict(act_by[a])}{mark}")
            if top and _algo_in_track(a, tr):
                out.append(f"       차단 top: {top}")

    # ── fresh backtest (옵션, BTC 현물 기준) ────────────────────
    if args.fresh_backtest:
        out.append("\n## 9. FRESH macro 백필 백테스트 (BTC 현물 기준)")
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from backtest_with_macro_backfill import build_macro_rows  # noqa: E402

            from arena import backtest, frequency  # noqa: E402

            parquet = Path(args.parquet)
            if parquet.exists():
                rows = build_macro_rows(parquet)
                warm = parameters.MACD_SLOW_PERIOD + parameters.MACD_SIGNAL_PERIOD
                prof = frequency.get_frequency_profile(frequency.LIVE_4H_PROFILE_ID)
                frames = await backtest.load_frames_from_supabase(
                    positions.db(),
                    symbol=parameters.BINANCE_SYMBOL,
                    interval=parameters.BINANCE_KLINE_INTERVAL,
                    limit=2000,
                    warmup_bars=warm,
                    indicator_profile_id=prof.default_indicator_profile_id,
                    macro_rows=rows,
                )
                res = backtest.run_replay(frames, settings=backtest.BacktestSettings())
                fb = defaultdict(list)
                for t in res.trades:
                    fb[t.algo_id].append(t)
                out.append(
                    f"frames={len(frames)} {frames[0].bar.close_time.date()}~"
                    f"{frames[-1].bar.close_time.date()} ver={parameters.PARAMS_VERSION}"
                )
                for a in ALGOS:
                    xs = fb.get(a, [])
                    if not xs:
                        continue
                    sw = sum(t.ret_pct * t.position_weight for t in xs) * 100
                    wn = sum(1 for t in xs if t.ret_pct > 0) / len(xs) * 100
                    out.append(f"  {a}: n={len(xs)} win={wn:.0f}% 가중합={sw:+.2f}%")
            else:
                out.append(f"(parquet 없음: {parquet})")
        except Exception as exc:
            out.append(f"(fresh backtest 실패: {exc})")

    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
