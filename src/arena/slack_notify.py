"""Slack Block Kit 알림 — Arena 트레이딩 이벤트 (한국어).

포지션 오픈/클로즈 시 Block Kit 리치 메세지 전송.
SLACK_BOT_TOKEN · SLACK_CHANNEL 미설정 시 무음 처리 (서비스 중단 없음).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from . import config, parameters

logger = logging.getLogger(__name__)

DASHBOARD_URL = "https://arena.sovereignwon.com"
VIRTUAL_CAPITAL = 1_000.0  # 알고당 가상 투자금 (USD)

# ── 알고리즘 한/영 라벨 ──────────────────────────────────────────────────────────

_ALGO_KO: dict[str, str] = {
    "supertrend": "슈퍼트렌드",
    "fng_contrarian": "FNG 역발산",
    "ema_cross": "EMA 삼중정렬",
    "macd_momentum": "MACD 모멘텀",
    "bb_squeeze": "BB 스퀴즈",
}

_ALGO_EN: dict[str, str] = {
    "supertrend": "SUPERTREND",
    "fng_contrarian": "FNG CONTRARIAN",
    "ema_cross": "EMA CROSS",
    "macd_momentum": "MACD MOMENTUM",
    "bb_squeeze": "BB SQUEEZE",
}

_MIN_HOLD: dict[str, float] = parameters.MIN_HOLD_HOURS

# ── 클라이언트 싱글턴 ────────────────────────────────────────────────────────────

_client: AsyncWebClient | None = None


def _get_client() -> AsyncWebClient | None:
    global _client
    if not config.SLACK_BOT_TOKEN or not config.SLACK_CHANNEL:
        return None
    if _client is None:
        _client = AsyncWebClient(token=config.SLACK_BOT_TOKEN)
    return _client


# ── 지표 한국어 설명 헬퍼 ────────────────────────────────────────────────────────


def _fng_label(fng: float | None) -> str:
    if fng is None:
        return "데이터 없음"
    v = float(fng)
    if v <= 25:
        return f"{int(v)} · 😱 극도의 공포"
    if v <= 45:
        return f"{int(v)} · 😨 공포"
    if v <= 55:
        return f"{int(v)} · 😐 중립"
    if v <= 75:
        return f"{int(v)} · 😏 탐욕"
    return f"{int(v)} · 🤑 극도의 탐욕"


def _vix_label(vix: float | None) -> str:
    if vix is None:
        return "데이터 없음"
    v = float(vix)
    if v < 15:
        return f"{v:.2f} · 🟢 매우 안정"
    if v < 20:
        return f"{v:.2f} · 🟡 안정"
    if v < 25:
        return f"{v:.2f} · 🟠 보통"
    if v < 30:
        return f"{v:.2f} · 🔴 높음"
    return f"{v:.2f} · 🚨 매우 높음"


def _rsi_label(rsi: float) -> str:
    if rsi >= 70:
        return f"{rsi:.1f} · ⚠️ 과매수"
    if rsi <= 30:
        return f"{rsi:.1f} · ⚠️ 과매도"
    if rsi > 55:
        return f"{rsi:.1f} · 📈 강세 구간"
    if rsi < 45:
        return f"{rsi:.1f} · 📉 약세 구간"
    return f"{rsi:.1f} · ⚖️ 중립"


def _regime_label(regime: str) -> str:
    return {
        "BullQuiet": "🐂 상승 안정 (BullQuiet)",
        "BearPanic": "🐻 하락 패닉 (BearPanic)",
        "Transitional": "🔄 전환 구간",
        "bull_trend": "📈 상승 추세",
        "bear_trend": "📉 하락 추세",
        "sideways": "↔️ 횡보",
        "stress": "⚡ 급변동 (Stress)",
    }.get(regime, regime or "—")


def _ret_bar(ret_pct: float) -> str:
    """수익률을 이모지 막대 그래프로 표현. ±3% 기준 10칸."""
    filled = min(10, int(abs(ret_pct * 100) / 0.3))
    bar = ("🟩" if ret_pct >= 0 else "🟥") * filled + "⬜" * (10 - filled)
    return bar


# ── 알고리즘별 신호 서술 ────────────────────────────────────────────────────────


def _signal_narrative(
    algo_id: str, direction: str, ind: dict[str, Any], macro: dict[str, Any]
) -> str:
    """알고리즘별 진입 근거를 한국어로 풀어서 설명."""
    dir_ko = "현물 매수" if direction == "long" else "현물 실행 제외 신호"
    rsi = ind.get("rsi", 50.0)

    if algo_id == "supertrend":
        st_dir_val = ind.get("supertrend_dir", 0)
        st_dir = "상승 ↑" if st_dir_val > 0 else "하락 ↓"
        upper = ind.get("supertrend_upper", 0.0)
        lower = ind.get("supertrend_lower", 0.0)
        price = ind.get("close", 0.0)
        if direction == "long" and price > 0 and upper > 0:
            upside = (upper - price) / price * 100
            return (
                f"슈퍼트렌드 방향이 *{st_dir}*으로 설정됨\n"
                f"현재가 ${price:,.0f}이 하단 지지밴드 ${lower:,.0f} 위 → {dir_ko} 유지\n"
                f"상단 저항밴드 ${upper:,.0f}까지 상승 여력 *+{upside:.1f}%*"
            )
        elif price > 0 and lower > 0:
            downside = (price - lower) / price * 100
            return (
                f"슈퍼트렌드 방향이 *{st_dir}*으로 전환됨\n"
                f"현재가 ${price:,.0f}이 상단 저항밴드 ${upper:,.0f} 아래 → {dir_ko}\n"
                f"하단 지지밴드 ${lower:,.0f}까지 하락 여력 *-{downside:.1f}%*"
            )
        return f"슈퍼트렌드 방향 *{st_dir}* → {dir_ko} 진입"

    if algo_id == "fng_contrarian":
        fng = macro.get("fng")
        fng_label = _fng_label(fng)
        if direction == "long":
            return (
                f"공포탐욕지수 *{fng_label}* 감지\n"
                f"시장이 극도의 공포에 빠졌을 때 역발산으로 {dir_ko} 진입\n"
                f'_"남들이 두려워할 때 탐욕스럽게" — 워런 버핏_'
            )
        return (
            f"공포탐욕지수 *{fng_label}* 감지\n"
            f"시장이 과도하게 낙관적일 때 현물 신규 진입을 보류하거나 보유 long을 청산\n"
            f'_"남들이 탐욕스러울 때 두려워하라" — 워런 버핏_'
        )

    if algo_id == "ema_cross":
        e21 = ind.get("ema_21", 0.0)
        e55 = ind.get("ema_55", 0.0)
        e200 = ind.get("ema_200", 0.0)
        if direction == "long":
            return (
                f"단기·중기·장기 이동평균이 *완전 상승 정렬* 확인됨\n"
                f"EMA 21 (${e21:,.0f}) `>` EMA 55 (${e55:,.0f}) `>` EMA 200 (${e200:,.0f})\n"
                f"강한 상승 추세 확인 → {dir_ko} 진입"
            )
        return (
            f"단기·중기·장기 이동평균이 *완전 하락 정렬* 확인됨\n"
            f"EMA 21 (${e21:,.0f}) `<` EMA 55 (${e55:,.0f}) `<` EMA 200 (${e200:,.0f})\n"
            f"강한 하락 추세 확인 → {dir_ko} 진입"
        )

    if algo_id == "macd_momentum":
        h = ind.get("macd_hist", 0.0)
        h_prev = ind.get("macd_hist_prev", h)
        bw = ind.get("bb_width", 0.0)
        trend = "모멘텀 *상승 중*" if h > h_prev else "모멘텀 *하락 중*"
        momentum_dir = "양수 (+)" if h >= 0 else "음수 (-)"
        return (
            f"MACD 히스토그램 {h:+.0f} ({momentum_dir}) — {trend}\n"
            f"BB 밴드폭 {bw:.2f}% (추세 활성 구간 확인)\n"
            f"RSI {_rsi_label(rsi)} — 과열 없이 {dir_ko} 진입"
        )

    if algo_id == "bb_squeeze":
        bb_w = ind.get("bb_width", 0.0)
        bb_pos = ind.get("bb_pos", 0.5)
        pos_desc = "상단" if bb_pos >= 0.6 else "하단"
        return (
            f"BB 밴드폭 *{bb_w:.2f}%* — 변동성 *압축 (스퀴즈)* 감지\n"
            f"가격이 밴드 *{pos_desc}* 위치 (pos={bb_pos:.2f}) + RSI {rsi:.1f} 확인\n"
            f"수렴 후 돌파 신호 — {dir_ko} 진입"
        )

    return f"RSI {_rsi_label(rsi)} → {dir_ko} 진입"


def _close_narrative(
    algo_id: str,
    direction: str,
    ret_pct: float,
    hold_hours: float,
    close_reason: str,
    is_stop_loss: bool,
) -> str:
    """청산 결과를 한국어로 풀어서 설명."""
    dir_ko = "현물 매수" if direction == "long" else "legacy synthetic short"
    algo_ko = _ALGO_KO.get(algo_id, algo_id)
    ret_str = f"{ret_pct * 100:+.2f}%"
    pnl_usd = ret_pct * VIRTUAL_CAPITAL
    pnl_str = f"{pnl_usd:+.2f}"

    if is_stop_loss:
        return (
            f"*{algo_ko}* 알고리즘의 {dir_ko} 포지션이 *🛑 손절* 처리됨\n"
            f"{hold_hours:.1f}시간 보유 후 *{ret_str}* ({pnl_str}$) 손실로 강제 청산\n"
            f"손절 기준: ATR × 2.5 동적 손절선 이탈"
        )

    reason_map = {
        "flat_signal": "신호 소멸 — 알고리즘이 진입 근거 없다고 판단",
        "reverse_signal": "방향 반전 신호 — 반대 포지션으로 전환",
    }
    reason_ko = reason_map.get(close_reason, close_reason or "신호 변화")
    result_word = "수익" if ret_pct >= 0 else "손실"

    return (
        f"*{algo_ko}* 알고리즘이 {dir_ko} 포지션을 청산함\n"
        f"{hold_hours:.1f}시간 보유 후 *{ret_str}* ({pnl_str}$) *{result_word}*으로 종료\n"
        f"청산 사유: {reason_ko}"
    )


# ── Block Kit 빌더 헬퍼 ─────────────────────────────────────────────────────────


def _header(text: str) -> dict[str, Any]:
    return {"type": "header", "text": {"type": "plain_text", "text": text, "emoji": True}}


def _divider() -> dict[str, Any]:
    return {"type": "divider"}


def _section_text(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _section_fields(*fields: tuple[str, str]) -> dict[str, Any]:
    return {
        "type": "section",
        "fields": [{"type": "mrkdwn", "text": f"*{label}*\n{value}"} for label, value in fields],
    }


def _context(*parts: str) -> dict[str, Any]:
    return {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "  ·  ".join(p for p in parts if p)}],
    }


def _button_link(label: str, url: str, style: str = "primary") -> dict[str, Any]:
    return {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": label, "emoji": True},
                "url": url,
                "style": style,
            }
        ],
    }


def _now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ── Public API ────────────────────────────────────────────────────────────────


async def notify_open(
    *,
    algo_id: str,
    direction: str,
    price: float,
    stop_loss_price: float,
    ind: dict[str, Any],
    macro: dict[str, Any],
    position_id: int | None,
    strategy_version: str,
) -> None:
    """포지션 오픈 시 Block Kit 알림 전송."""
    client = _get_client()
    if client is None:
        return
    if direction != "long":
        logger.warning(
            "Spot execution skipped non-long open notification: %s %s", algo_id, direction
        )
        return

    dir_emoji = "🟢"
    dir_ko = "현물 매수 진입"
    algo_ko = _ALGO_KO.get(algo_id, algo_id)
    algo_en = _ALGO_EN.get(algo_id, algo_id.upper())

    sl_dist_pct = abs(price - stop_loss_price) / price * 100
    sl_dist_usd = abs(price - stop_loss_price)
    sl_dir = "↓"

    rsi = ind.get("rsi", 0.0)
    atr = ind.get("atr", 0.0)
    atr_pct = ind.get("atr_pct", 0.0) * 100
    min_hold = _MIN_HOLD.get(algo_id, parameters.MIN_HOLD_FALLBACK_HOURS)

    fng = macro.get("fng")
    vix = macro.get("vix_now")
    regime = macro.get("regime_state", "")

    blocks: list[dict[str, Any]] = [
        # ① 헤더
        _header(f"{dir_emoji} {dir_ko}  ─  {algo_ko} ({algo_en})"),
        # ② 진입 정보 (2×2 필드)
        _section_fields(
            ("💰 진입가", f"${price:,.2f}"),
            (
                "🛑 손절가",
                f"${stop_loss_price:,.2f}  ({sl_dir} {sl_dist_pct:.2f}%  /  -{sl_dist_usd:,.0f}$)",
            ),
            ("📊 ATR 변동폭", f"${atr:,.2f}  ({atr_pct:.2f}%)"),
            ("⏰ 최소 보유", f"{min_hold:.0f}시간"),
        ),
        _divider(),
        # ③ 신호 근거 (알고별 서술형)
        _section_text(
            f"📈 *진입 신호 근거 — {algo_ko}*\n\n"
            + _signal_narrative(algo_id, direction, ind, macro)
        ),
        _divider(),
        # ④ 시장 환경 (2×2 필드)
        _section_fields(
            ("😱 공포탐욕지수", _fng_label(fng)),
            ("📉 VIX (변동성)", _vix_label(vix)),
            ("🎯 RSI", _rsi_label(rsi)),
            ("🌊 시장 레짐", _regime_label(regime)),
        ),
        _divider(),
        # ⑤ 대시보드 링크 버튼
        _button_link("🔗 대시보드 보기 →", DASHBOARD_URL),
        # ⑥ 컨텍스트 푸터
        _context(
            f"Position #{position_id}" if position_id else "신규 포지션",
            strategy_version,
            _now_utc_str(),
        ),
    ]

    fallback = f"{dir_emoji} {algo_ko} {dir_ko} @ ${price:,.2f}  손절 ${stop_loss_price:,.2f}"
    await _post(client, fallback, blocks)


async def notify_close(
    *,
    algo_id: str,
    direction: str,
    open_price: float,
    close_price: float,
    ret_pct: float,
    hold_hours: float,
    position_id: int | None,
    is_stop_loss: bool,
    close_reason: str = "",
) -> None:
    """포지션 청산 시 Block Kit 알림 전송."""
    client = _get_client()
    if client is None:
        return

    hit = ret_pct >= 0
    result_emoji = "✅" if hit else "❌"
    result_ko = "수익" if hit else "손실"
    dir_ko = "현물 매수" if direction == "long" else "legacy synthetic short"
    algo_ko = _ALGO_KO.get(algo_id, algo_id)
    algo_en = _ALGO_EN.get(algo_id, algo_id.upper())

    ret_str = f"{ret_pct * 100:+.2f}%"
    pnl_usd = ret_pct * VIRTUAL_CAPITAL
    pnl_str = f"{pnl_usd:+.2f}$"
    price_diff = close_price - open_price
    price_diff_str = f"{'+' if price_diff >= 0 else ''}{price_diff:,.2f}$"

    ret_bar = _ret_bar(ret_pct)

    blocks: list[dict[str, Any]] = [
        # ① 헤더
        _header(f"{result_emoji} {dir_ko} 청산  ─  {algo_ko}  ({ret_str} {result_ko})"),
        # ② 손익 바 (시각적 강조)
        _section_text(
            f"{ret_bar}\n`{ret_str}`  /  가상 손익: *{pnl_str}*  (가상 자본 ${VIRTUAL_CAPITAL:,.0f} 기준)"
        ),
        _divider(),
        # ③ 거래 수치 (2×2 필드)
        _section_fields(
            ("📥 진입가", f"${open_price:,.2f}"),
            ("📤 청산가", f"${close_price:,.2f}  ({price_diff_str})"),
            ("💹 수익률", ret_str),
            ("⏱ 보유시간", f"{hold_hours:.1f}시간"),
        ),
        _divider(),
        # ④ 청산 서술
        _section_text(
            "💬 *거래 요약*\n\n"
            + _close_narrative(algo_id, direction, ret_pct, hold_hours, close_reason, is_stop_loss)
        ),
        _divider(),
        # ⑤ 대시보드 링크 버튼
        _button_link("🔗 대시보드 보기 →", DASHBOARD_URL, style="primary" if hit else "danger"),
        # ⑥ 컨텍스트 푸터
        _context(
            f"Position #{position_id}" if position_id else "",
            "🛑 손절 청산" if is_stop_loss else "정상 청산",
            algo_en,
            _now_utc_str(),
        ),
    ]

    fallback = f"{result_emoji} {algo_ko} {dir_ko} 청산  {ret_str}  보유 {hold_hours:.1f}h"
    await _post(client, fallback, blocks)


# ── 내부 전송 헬퍼 ───────────────────────────────────────────────────────────────


async def _post(client: AsyncWebClient, text: str, blocks: list[dict[str, Any]]) -> None:
    try:
        await client.chat_postMessage(
            channel=config.SLACK_CHANNEL,
            text=text,
            blocks=blocks,
            unfurl_links=False,
            unfurl_media=False,
        )
    except SlackApiError as exc:
        logger.warning("Slack 알림 실패: %s", exc.response.get("error", exc))
    except Exception as exc:
        logger.warning("Slack 알림 오류: %s", exc)
