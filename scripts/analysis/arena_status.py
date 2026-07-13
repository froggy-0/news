"""arena-status: 실행시점 아레나 거래 현황 + 히스토리 분석 (지속적 알고 개선용).

한 번의 실행에서 asyncio.gather로 병렬 조회 → 압축 요약 출력. 스키마·컬럼은 스킬
(.claude/skills/arena-status/SKILL.md)에 문서화돼 있어 재탐색 불필요.

섹션:
  1) 오픈 포지션 + 실시간 미실현손익 (Binance 현재가 기준)
  2) 청산 거래 알고별 성과 — 표준지표 포함(expectancy·profit factor·payoff·노출률)
     + params_version 분리 + buy&hold 벤치마크
  3) MFE/MAE 청산 품질 (보유기간 4h봉 high/low 기준 최대 유리/불리 이동, MFE 포착률)
  4) 현재 macro/레짐 스냅샷 (진입 게이트 컨텍스트)
  5) 라이브 vs 저장 백테스트 대조 (staleness 명시)
  6) 진입조건→결과 분석 (레짐별·macd_hist부호별·close_reason별)
  7) 라이브 차단 사유 (arena_decisions — 무엇이 진입을 막고 있나)

옵션:
  --fresh-backtest : macro 백필 백테스트 즉석 재계산(~30-60s, 정확한 대조). 기본은 저장본.
  --algo <id>      : 특정 알고만 상세.
  --days <n>       : 차단 사유 집계 기간(기본 14일).

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

from arena import positions  # noqa: E402

ALGOS = ["regime_trend", "fng_contrarian", "vix_rsi", "macd_momentum", "multi_factor", "omnibus"]
PRICE_URL = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"


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


async def _price() -> float | None:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(PRICE_URL)
            r.raise_for_status()
            return float(r.json()["price"])
    except Exception:
        return None


async def _open_positions() -> list[dict]:
    res = (
        await positions.db()
        .table("paper_positions")
        .select(
            "id,algo_id,direction,open_time,open_price,stop_loss_price,position_weight,"
            "trail_distance,signal_reason,params_version"
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
            "position_weight,hold_hours,close_reason,params_version,macro_snapshot,signal_reason"
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


async def _latest_backtest() -> tuple[dict | None, list[dict]]:
    runs = (
        await positions.db()
        .table("arena_backtest_runs")
        .select("backtest_run_id,created_at,data_start,data_end,params_version,status")
        .eq("status", "completed")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    run = (runs.data or [None])[0]
    if not run:
        return None, []
    tr = (
        await positions.db()
        .table("arena_backtest_trades")
        .select("algo_id,ret_pct,net_ret_pct,exit_reason")
        .eq("backtest_run_id", run["backtest_run_id"])
        .limit(5000)
        .execute()
    )
    return run, (tr.data or [])


async def _decisions(days: int) -> list[dict]:
    """arena_decisions — 사이클마다 알고별 행동·차단사유 로그(라이브 near-miss)."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    res = (
        await positions.db()
        .table("arena_decisions")
        .select("algo_id,action,skipped_reason,created_at")
        .gte("created_at", since)
        .limit(10000)
        .execute()
    )
    return res.data or []


async def _bars_since(start_iso: str) -> list[dict]:
    """MFE/MAE·벤치마크용 4h 봉. open_time 기준 dedup은 호출측."""
    res = (
        await positions.db()
        .table("arena_ohlcv_bars")
        .select("open_time,high,low,close")
        .eq("symbol", "BTCUSDT")
        .eq("interval", "4h")
        .gte("open_time", start_iso)
        .order("open_time")
        .limit(6000)
        .execute()
    )
    seen: dict[str, dict] = {}
    for r in res.data or []:
        seen[r["open_time"]] = r  # 중복 봉(run별 기록) 마지막 값으로 dedup
    return sorted(seen.values(), key=lambda r: r["open_time"])


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

    4h 봉 단위라 인트라바 극값은 과소평가될 수 있음(보수적 추정) — 추세 판단엔 충분.
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
    return hi / op - 1.0, lo / op - 1.0  # (MFE, MAE) — long 기준


def _latest_parquet() -> str:
    """data/sentiment_join/ 에서 가장 최근(mtime) master*.parquet 자동 선택.

    2026-07-14: 이전엔 고정 파일명(sentiment_join_master_20260502.parquet)이 기본값이었는데,
    더 최신 parquet(master_20260710.parquet 등)이 추가돼도 갱신되지 않아 --fresh-backtest가
    2.5개월 stale macro로 조용히 실행되던 문제가 있었음(라이브-백테스트 괴리를 진짜처럼 보이게 함).
    """
    d = Path(__file__).resolve().parents[2] / "data" / "sentiment_join"
    candidates = list(d.glob("master_*.parquet")) + list(d.glob("sentiment_join_master_*.parquet"))
    if not candidates:
        return "data/sentiment_join/sentiment_join_master_20260502.parquet"
    return str(max(candidates, key=lambda p: p.stat().st_mtime))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--algo", default="")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--fresh-backtest", action="store_true")
    ap.add_argument(
        "--parquet",
        default=None,
        help="기본: data/sentiment_join/ 내 최신 master*.parquet 자동 선택",
    )
    args = ap.parse_args()
    if args.parquet is None:
        args.parquet = _latest_parquet()
    return asyncio.run(_run(args))


async def _run(args) -> int:
    now = datetime.now(timezone.utc)
    await positions.init()
    price, opens, closed, macro, (bt_run, bt_trades), decisions = await asyncio.gather(
        _price(),
        _open_positions(),
        _closed_trades(),
        _latest_macro(),
        _latest_backtest(),
        _decisions(args.days),
    )
    # MFE/MAE·벤치마크용 봉 — 첫 거래 시점부터 (거래 없으면 스킵)
    first_open = min((t["open_time"] for t in closed + opens if t.get("open_time")), default=None)
    bars = await _bars_since(first_open) if first_open else []

    out: list[str] = []
    out.append(f"# arena-status @ {now.strftime('%Y-%m-%d %H:%M UTC')}  BTC={price}")

    # ── 1. 오픈 포지션 ──────────────────────────────────────────
    out.append(f"\n## 1. 오픈 포지션 ({len(opens)})")
    if opens:
        out.append("algo | dir | 진입가 | 현재손익% | 보유h | 손절까지% | 목표가 | 비중 | ver")
        for p in opens:
            op, sl = p["open_price"], p.get("stop_loss_price")
            tgt = (p.get("signal_reason") or {}).get("omni_target_price")
            upnl = ((price / op - 1) * 100) if (price and op) else None
            to_stop = ((price - sl) / price * 100) if (price and sl) else None
            hold = _age_h(p.get("open_time"), now)
            out.append(
                f"{p['algo_id']} | {p['direction']} | {op:.0f} | "
                f"{('%+.2f' % upnl) if upnl is not None else '?'} | "
                f"{hold:.0f} | {('%+.2f' % to_stop) if to_stop is not None else '?'} | "
                f"{('%.0f' % tgt) if tgt else '-'} | {p.get('position_weight') or 1:.2f} | "
                f"{p.get('params_version') or '?'}"
            )
    else:
        out.append("(없음)")

    # ── 2. 청산 성과 + 표준지표 + 벤치마크 ──────────────────────
    out.append(f"\n## 2. 청산 거래 알고별 성과 (총 {len(closed)}건)")
    out.append("algo | n | win% | 가중합% | 기대값%/T | PF | payoff | 평균h | 노출% | close_reason")
    by_algo = defaultdict(list)
    for t in closed:
        by_algo[t["algo_id"]].append(t)
    span_h = max((_age_h(first_open, now) or 1.0), 1.0)
    for a in ALGOS:
        ts = by_algo.get(a, [])
        s = _agg(ts)
        cr = dict(Counter(t.get("close_reason") for t in ts))
        expo = sum(t.get("hold_hours") or 0 for t in ts) / span_h * 100
        pf = f"{s['pf']:.2f}" if s["pf"] != float("inf") else "inf"
        out.append(
            f"{a} | {s['n']} | {s['win']:.0f} | {s['sum_w']:+.2f} | {s['expectancy']:+.2f} | "
            f"{pf} | {s['payoff']:.2f} | {s['hold']:.0f} | {expo:.0f} | {cr}"
        )
    # buy & hold 벤치마크 (동기간)
    if bars and price:
        base = float(bars[0]["close"])
        bh = (price / base - 1) * 100
        out.append(
            f"벤치마크 buy&hold: {bh:+.2f}% (기간 {str(first_open)[:10]}~, 시작가 {base:.0f})"
            " — 알고 가중합%와 직접 비교 (노출률 감안)"
        )
    vers = sorted({t.get("params_version") for t in closed if t.get("params_version")})
    if len(vers) > 1:
        out.append("\n### params_version별 (변경 효과)")
        for v in vers:
            vs = _agg([t for t in closed if t.get("params_version") == v])
            out.append(f"  {v}: n={vs['n']} win={vs['win']:.0f}% 가중합={vs['sum_w']:+.2f}%")

    # ── 3. MFE/MAE 청산 품질 ────────────────────────────────────
    out.append("\n## 3. MFE/MAE 청산 품질 (보유중 최대 유리/불리, 4h봉 기준)")
    out.append("algo | n | 평균MFE% | 평균MAE% | MFE포착률% | MFE>1% 미실현 승리 | 해석힌트")
    for a in ALGOS:
        ts = by_algo.get(a, [])
        rows = []
        missed = 0
        for t in ts:
            mm = _mfe_mae(t, bars)
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
        # MFE 포착률 = 실현수익 / MFE (MFE>0인 거래만) — 낮으면 이익을 흘리는 청산.
        caps = [r[2] / r[0] for r in rows if r[0] > 0.003]
        cap = statistics.mean(caps) * 100 if caps else 0.0
        hint = ""
        if cap < 30:
            hint = "청산이 이익 흘림(포착률<30%) → 목표가/트레일 검토"
        if avg_mae < -3 and any(r[2] > 0 for r in rows):
            hint += " | MAE 깊게 견딤 → 손절/사이징 검토"
        out.append(
            f"{a} | {len(rows)} | {avg_mfe:+.2f} | {avg_mae:+.2f} | {cap:.0f} | {missed} | {hint}"
        )

    # ── 4. 현재 macro/레짐 ──────────────────────────────────────
    out.append("\n## 4. 현재 macro/레짐")
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
    else:
        out.append("(macro 없음)")

    # ── 5. 라이브 vs 저장 백테스트 ──────────────────────────────
    out.append("\n## 5. 라이브 vs 저장 백테스트")
    if bt_run:
        bage = _age_h(bt_run.get("created_at"), now)
        warn = " ⚠️STALE(주간잡 확인 필요)" if (bage or 0) > 24 * 8 else ""
        out.append(
            f"백테스트 기준 {bt_run.get('created_at')} ({(bage or 0) / 24:.0f}일전){warn} "
            f"ver={bt_run.get('params_version')} macro=저장본(라이브와 다를 수 있음)"
        )
        bt_by = defaultdict(list)
        for t in bt_trades:
            bt_by[t["algo_id"]].append(t)
        out.append("algo | live 가중합% | live win% | bt n | bt sum% | bt win%")
        for a in ALGOS:
            ls = _agg(by_algo.get(a, []))
            bts = bt_by.get(a, [])
            bn = len(bts)
            bsum = sum(t.get("ret_pct") or 0 for t in bts) * 100
            bwin = (sum(1 for t in bts if (t.get("ret_pct") or 0) > 0) / bn * 100) if bn else 0
            out.append(
                f"{a} | {ls['sum_w']:+.2f} | {ls['win']:.0f} | {bn} | {bsum:+.2f} | {bwin:.0f}"
            )
    else:
        out.append("(저장 백테스트 없음 — --fresh-backtest 사용)")

    # ── 6. 진입조건→결과 분석 ───────────────────────────────────
    out.append("\n## 6. 진입조건→결과 분석 (알고 개선 신호)")
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
        cr_loss = Counter(t.get("close_reason") for t in losers)
        line = f"  [{a}] n={len(ts)} 손실={len(losers)}"
        if mh_neg_win is not None:
            line += f" | 진입시MACD음수 {len(mh_neg)}건 승률{mh_neg_win:.0f}%"
        line += f" | 진입레짐{dict(reg)} | 손실close_reason{dict(cr_loss)}"
        out.append(line)

    # ── 7. 라이브 차단 사유 (arena_decisions) ────────────────────
    out.append(f"\n## 7. 라이브 차단 사유 — 최근 {args.days}일 (무엇이 진입을 막나)")
    dec_by = defaultdict(Counter)
    act_by = defaultdict(Counter)
    for d in decisions:
        a = d.get("algo_id")
        if a not in ALGOS:
            continue
        act_by[a][d.get("action")] += 1
        if d.get("action") in ("flat_skip", "risk_blocked") and d.get("skipped_reason"):
            dec_by[a][d["skipped_reason"]] += 1
    for a in algos_scope:
        if a not in act_by:
            continue
        top = dec_by[a].most_common(4)
        acts = dict(act_by[a])
        out.append(f"  [{a}] actions={acts}")
        if top:
            out.append(f"      차단 top: {top}")

    # ── fresh backtest (옵션) ───────────────────────────────────
    if args.fresh_backtest:
        out.append("\n## 5b. FRESH macro 백필 백테스트")
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from backtest_with_macro_backfill import build_macro_rows  # noqa: E402

            from arena import backtest, frequency, parameters  # noqa: E402

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
                    sw = sum(t.ret_pct * t.position_weight for t in xs) * 100
                    wn = (sum(1 for t in xs if t.ret_pct > 0) / len(xs) * 100) if xs else 0
                    out.append(f"  {a}: n={len(xs)} win={wn:.0f}% 가중합={sw:+.2f}%")
            else:
                out.append(f"(parquet 없음: {parquet})")
        except Exception as exc:
            out.append(f"(fresh backtest 실패: {exc})")

    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
