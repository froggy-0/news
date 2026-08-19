"""arena 정기 헬스체크 — 과거 발견된 버그 클래스를 자동 재점검 (2026-08-19, P7).

배경: 이 프로젝트가 지금까지 찾은 실제 라이브 버그(멀티자산 심볼 필터링,
depth 과소추정, RLS 미설정, PARAMS_VERSION 배포 누락 가능성 등)는 전부
"우연히 세션 중 발견"이었다. 신뢰도 제고 방안 3순위(정기 헬스체크 루틴화)로
이 패턴들을 코드화해 반복 실행 가능하게 만든다.

점검 항목(전부 Supabase 직접 조회, EC2 접근 불필요):
  1. PARAMS_VERSION 드리프트 — 최근 포지션의 params_version이 로컬 코드와 다른데
     최근 활동이 있다면 배포 누락 의심.
  2. 실행게이트 reject_reason 이상 — depth/slippage/spread 계열 사유 재등장 시
     2026-07-30/2026-08-14에 고친 버그의 재발 의심.
  3. ALGORITHM_TRACK_SCOPE 위반 — 스코프 밖 (symbol, algo_id)로 최근 신규 진입.
  4. PERP_LONG_BLOCKED_TRACKS 위반 — 숏 전용 트랙에 최근 롱 진입.
  5. 활동 정지(staleness) — 전체 최신 활동이 오래됐으면 서비스 중단 의심.
  6. meridian 레그 동시진입 캡 위반 — reversion/short 레그가 cap 초과 동시보유.

종료 코드: 0(전부 PASS/WARN), 1(FAIL 1건 이상) — cron/스케줄 에이전트가
결과를 바로 판별할 수 있게.

재현: .venv/bin/python3 scripts/analysis/arena_health_check.py
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from arena import parameters, positions  # noqa: E402

# 지금까지 실측으로 확인된 "정상" 거부 사유(2026-08-14 depth 재보정 이후).
# 이 목록 밖의 사유가 새로 나타나면 과거 버그 클래스 재발 가능성으로 WARN.
KNOWN_GOOD_REJECT_REASONS = {"expected_return_below_cost_floor"}
DEPTH_BUG_SIGNATURE_SUBSTRINGS = ("depth", "slippage", "spread")

FRESHNESS_LIMIT_HOURS = 10  # 4h 캐던스 2주기 + 여유
SCOPE_GRACE_HOURS = 24  # 이 시간 이내 신규 진입만 "최근"으로 간주(레거시 포지션 오탐 방지)
# 2026-08-14 depth 재보정 이전 데이터가 창에 섞이면 오탐(구 버그를 재발로 오판) —
# 5일로 두면 2026-08-14 이후만 걸린다. 시간이 지나 창이 완전히 재보정 이후로만
# 채워지면 다시 늘려도 됨(하드코딩된 고정 날짜 대신 롤링 윈도우 유지).
REJECT_REASON_WINDOW_DAYS = 5


def _dt(ts: str | None) -> datetime | None:
    if not ts:
        return None
    d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


async def check_params_version_drift(now: datetime) -> tuple[str, str]:
    res = (
        await positions.db()
        .table("paper_positions")
        .select("params_version,open_time,symbol,algo_id")
        .order("open_time", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return "WARN", "포지션 데이터 없음"
    row = rows[0]
    age_h = (now - _dt(row["open_time"])).total_seconds() / 3600.0
    live_version = row.get("params_version")
    local_version = parameters.PARAMS_VERSION
    if live_version == local_version:
        return "PASS", f"최신 포지션 버전 일치 ({live_version}, {age_h:.1f}h 전)"
    if age_h > FRESHNESS_LIMIT_HOURS:
        return "WARN", (
            f"최신 포지션이 {age_h:.1f}h 전이라 버전 비교 무의미 "
            f"(live={live_version} local={local_version})"
        )
    return "FAIL", (
        f"최근({age_h:.1f}h 전) 포지션 버전({live_version})이 로컬 코드({local_version})와 "
        "다름 — 배포 누락 의심"
    )


async def check_execution_gate_reject_reasons(now: datetime) -> tuple[str, str]:
    since = (now - timedelta(days=REJECT_REASON_WINDOW_DAYS)).isoformat()
    res = (
        await positions.db()
        .table("arena_execution_gates")
        .select("reject_reason")
        .eq("decision", "no_trade")
        .not_.is_("signal", "null")
        .gte("created_at", since)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return "PASS", f"최근 {REJECT_REASON_WINDOW_DAYS}일 실신호 거부 기록 없음"
    counts = Counter(r.get("reject_reason") for r in rows)
    unknown = {reason: n for reason, n in counts.items() if reason not in KNOWN_GOOD_REJECT_REASONS}
    depth_bug_hits = {
        reason: n
        for reason, n in counts.items()
        if reason and any(sig in reason for sig in DEPTH_BUG_SIGNATURE_SUBSTRINGS)
    }
    summary = ", ".join(f"{r}={n}" for r, n in counts.most_common())
    if depth_bug_hits:
        return "FAIL", f"depth/slippage/spread 계열 거부 재등장: {depth_bug_hits} (전체: {summary})"
    if unknown:
        return "WARN", f"미확인 거부사유: {unknown} (전체: {summary})"
    return "PASS", f"전부 정상 사유 (전체: {summary})"


async def check_algorithm_track_scope(now: datetime) -> tuple[str, str]:
    res = (
        await positions.db()
        .table("paper_positions")
        .select("id,algo_id,symbol,open_time")
        .eq("status", "open")
        .execute()
    )
    rows = res.data or []
    violations = []
    for row in rows:
        age_h = (now - _dt(row["open_time"])).total_seconds() / 3600.0
        if age_h > SCOPE_GRACE_HOURS:
            continue  # 레거시 포지션(스코프 변경 이전 진입) — 정상, 관리만 계속
        if not parameters.algorithm_in_track_scope(row["algo_id"], row["symbol"]):
            violations.append(row)
    if violations:
        detail = ", ".join(f"id={v['id']} {v['symbol']}/{v['algo_id']}" for v in violations)
        return "FAIL", f"ALGORITHM_TRACK_SCOPE 밖 최근 신규진입 {len(violations)}건: {detail}"
    return "PASS", f"오픈 포지션 {len(rows)}건 전부 스코프 내(또는 24h 이전 레거시)"


async def check_perp_long_blocked_tracks(now: datetime) -> tuple[str, str]:
    res = (
        await positions.db()
        .table("paper_positions")
        .select("id,algo_id,symbol,direction,open_time")
        .eq("direction", "long")
        .gte("open_time", (now - timedelta(hours=SCOPE_GRACE_HOURS)).isoformat())
        .execute()
    )
    rows = res.data or []
    violations = [
        r for r in rows if (r["symbol"], r["algo_id"]) in parameters.PERP_LONG_BLOCKED_TRACKS
    ]
    if violations:
        detail = ", ".join(f"id={v['id']} {v['symbol']}/{v['algo_id']}" for v in violations)
        return "FAIL", f"PERP_LONG_BLOCKED_TRACKS 위반 최근 롱진입 {len(violations)}건: {detail}"
    return "PASS", f"최근 24h 롱진입 {len(rows)}건 전부 차단트랙 아님"


async def check_freshness(now: datetime) -> tuple[str, str]:
    res = (
        await positions.db()
        .table("paper_positions")
        .select("open_time")
        .order("open_time", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return "FAIL", "포지션 데이터 자체가 없음"
    age_h = (now - _dt(rows[0]["open_time"])).total_seconds() / 3600.0
    if age_h > FRESHNESS_LIMIT_HOURS:
        return "FAIL", f"최신 활동이 {age_h:.1f}h 전 — 서비스 중단 의심(4h 캐던스 2주기 초과)"
    return "PASS", f"최신 활동 {age_h:.1f}h 전"


async def check_meridian_leg_concurrency(now: datetime) -> tuple[str, str]:
    res = (
        await positions.db()
        .table("paper_positions")
        .select("id,symbol,signal_reason,open_time")
        .eq("status", "open")
        .eq("algo_id", "meridian")
        .execute()
    )
    rows = res.data or []
    by_leg: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        leg = (row.get("signal_reason") or {}).get("active_leg")
        if leg:
            by_leg[leg].append(row)
    violations = []
    for leg, leg_rows in by_leg.items():
        cap = parameters.MERIDIAN_LEG_CONCURRENCY_CAP_BY_LEG.get(leg)
        if cap is not None and len(leg_rows) > cap:
            violations.append((leg, leg_rows))
    if violations:
        detail = "; ".join(
            f"{leg}: {len(rs)}건({[r['symbol'] for r in rs]}) cap={parameters.MERIDIAN_LEG_CONCURRENCY_CAP_BY_LEG[leg]}"
            for leg, rs in violations
        )
        return "FAIL", f"meridian 레그 동시진입 캡 초과: {detail}"
    return "PASS", f"meridian 오픈 {len(rows)}건, 레그별 캡 위반 없음"


async def main() -> int:
    await positions.init()
    now = datetime.now(timezone.utc)

    checks = [
        ("PARAMS_VERSION 드리프트", check_params_version_drift),
        ("실행게이트 거부사유 이상", check_execution_gate_reject_reasons),
        ("ALGORITHM_TRACK_SCOPE 위반", check_algorithm_track_scope),
        ("PERP_LONG_BLOCKED_TRACKS 위반", check_perp_long_blocked_tracks),
        ("활동 정지(staleness)", check_freshness),
        ("meridian 레그 동시진입 캡", check_meridian_leg_concurrency),
    ]

    print(
        f"=== arena 헬스체크 {now.isoformat()} (local PARAMS_VERSION={parameters.PARAMS_VERSION}) ===\n"
    )
    worst = "PASS"
    order = {"PASS": 0, "WARN": 1, "FAIL": 2}
    for label, fn in checks:
        try:
            status, msg = await fn(now)
        except Exception as exc:  # noqa: BLE001
            status, msg = "FAIL", f"체크 실행 중 예외: {exc!r}"
        if order[status] > order[worst]:
            worst = status
        print(f"[{status:4s}] {label}: {msg}")

    print(f"\n종합: {worst}")
    return 1 if worst == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
