import Link from "next/link";
import { ArrowRight, BarChart2, Activity } from "lucide-react";
import React from "react";
import type { BriefData, RiskOverlay, SovereignIndex } from "@schema/brief.types";

import { SubscriptionForm } from "@/components/layout/SubscriptionForm";
import { displayHeadline, formatPublicationDate, hasUsableHeadline } from "@/lib/format";

const operatingPrinciples = [
  {
    num: "01",
    title: "시장 내러티브 감지",
    desc: "속보보다 먼저, Bloomberg와 Reuters가 시장을 어떤 톤으로 읽기 시작했는지를 포착합니다.",
  },
  {
    num: "02",
    title: "가격 신호 교차 확인",
    desc: "비트코인, ETF 자금 흐름, 변동성, 달러, 금리가 같은 방향을 가리키는지 함께 점검합니다.",
  },
  {
    num: "03",
    title: "브리프 압축 정리",
    desc: "흩어진 데이터를 하나의 판단으로 묶어 다음 거래일 전에 읽을 수 있게 정리합니다.",
  },
];

const comparisonRows = {
  common: ["속보와 팩트 나열", "단일 뉴스 흐름 중심", "내러티브 형성 이후 해석", "중요한 것과 노이즈를 구분하지 않음"],
  sovereign: [
    "Bloomberg, Reuters 보도를 실시간 추적",
    "Binance, BlackRock 등 공식 데이터로 검증",
    "시장 내러티브 형성 이전에 판단",
    "노이즈는 걸러내고, 시장이 조용할 때도 의미를 읽음",
  ],
};

export function HomeHero({
  brief,
  heroSeed,
  latestDate,
}: {
  brief: BriefData;
  heroSeed: string;
  latestDate: string;
}) {
  const heroHeadline = hasUsableHeadline(brief.meta.displayHeadline || brief.aiJudgment.headline)
    ? displayHeadline(brief.meta.displayHeadline || brief.aiJudgment.headline)
    : `${formatPublicationDate(brief.meta.date)} Brief`;
  const marketItems = brief.marketSnapshot.items.slice(0, 4);
  const featuredNews = brief.featuredNews?.slice(0, 3) ?? [];

  return (
    <>
      <section className="hero-stage px-6 md:px-20" data-hero-seed={heroSeed}>
        <div className="relative z-10 flex w-full max-w-3xl flex-col items-center text-center">

          {/* Eyebrow — date + live pulse */}
          <div className="flex items-center gap-2.5">
            <span
              className="h-1.5 w-1.5 rounded-full bg-[#00ffff]"
              style={{ boxShadow: "0 0 5px rgba(0,255,255,0.7)" }}
            />
            <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-[var(--taupe)]/60">
              BTC Market Intelligence · Daily
            </span>
          </div>

          <h1 className="mt-8 text-4xl font-bold leading-[1.12] text-[var(--smoke)] md:mt-10 md:text-[76px] md:leading-[1.10]">
            SOVEREIGN BRIEF
          </h1>
          <p className="mt-3 text-4xl font-bold leading-[1.12] text-[var(--taupe)]/70 md:text-[76px] md:leading-[1.10]">
            시장이 움직이기 전에.
          </p>

          <p className="mt-8 max-w-xs break-keep text-[15px] leading-relaxed text-[var(--taupe)]/72 md:mt-10 md:max-w-[520px] md:text-[17px]">
            Bloomberg, Reuters 보도와 Binance, BlackRock 공식 데이터를 교차해<br className="hidden md:block" />
            내러티브가 가격에 반영되기 전에 정리합니다.
          </p>

          {/* Inline live signal — fold 내 브랜딩 핵심 */}
          {(brief.sovereignIndex || brief.riskOverlay) && (
            <div className="mt-10 flex items-center gap-0 overflow-hidden rounded-xl border border-white/[0.07] bg-white/[0.03] backdrop-blur-sm">
              {brief.sovereignIndex && (
                <div className="flex items-center gap-3 px-5 py-3">
                  <div
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ background: ZONE_COLOR[brief.sovereignIndex.zone], boxShadow: `0 0 6px ${ZONE_COLOR[brief.sovereignIndex.zone]}80` }}
                  />
                  <span className="font-mono text-[9px] uppercase tracking-[0.18em] text-white/32">Index</span>
                  <span className="flex items-baseline gap-1">
                    <span
                      className="font-mono text-[18px] font-bold tabular-nums leading-none"
                      style={{ color: ZONE_COLOR[brief.sovereignIndex.zone] }}
                    >
                      {Math.round(brief.sovereignIndex.score)}
                    </span>
                    {brief.sovereignIndex.scoreDelta != null && (
                      <span
                        className="font-mono text-[11px] font-semibold tabular-nums leading-none"
                        style={{ color: brief.sovereignIndex.scoreDelta >= 0 ? "#10b981" : "#f87171" }}
                      >
                        {brief.sovereignIndex.scoreDelta >= 0 ? "↑" : "↓"}{Math.abs(Math.round(brief.sovereignIndex.scoreDelta))}
                      </span>
                    )}
                  </span>
                  <span className="whitespace-nowrap font-mono text-[10px] text-white/38">
                    {ZONE_LABEL[brief.sovereignIndex.zone]}
                  </span>
                </div>
              )}
              {brief.sovereignIndex && brief.riskOverlay && (
                <div className="h-8 w-px bg-white/[0.08]" />
              )}
              {brief.riskOverlay && (
                <div className="flex items-center gap-3 px-5 py-3">
                  <span className="font-mono text-[9px] uppercase tracking-[0.18em] text-white/32">State</span>
                  <span
                    className="whitespace-nowrap text-[14px] font-bold leading-none"
                    style={{ color: REGIME_COLOR[brief.riskOverlay.regimeState] ?? "rgba(255,255,255,0.72)" }}
                  >
                    {REGIME_LABEL[brief.riskOverlay.regimeState] ?? brief.riskOverlay.regimeState}
                  </span>
                  {brief.riskOverlay.signalConfidence && brief.riskOverlay.signalConfidence !== "NONE" && (
                    <>
                      <div className="h-3 w-px bg-white/[0.08]" />
                      <span
                        className="whitespace-nowrap font-mono text-[10px] font-semibold"
                        style={{ color: CONF_COLOR[brief.riskOverlay.signalConfidence] ?? "rgba(255,255,255,0.46)" }}
                      >
                        {CONF_LABEL[brief.riskOverlay.signalConfidence]}
                      </span>
                    </>
                  )}
                </div>
              )}
            </div>
          )}

          <div id="subscribe" className="mt-10 w-full max-w-md md:mt-12 md:max-w-[480px]">
            <SubscriptionForm />
          </div>
          <p className="mt-4 font-mono text-[11px] uppercase tracking-[0.12em] text-[var(--taupe)]/36">
            매일 아침 · 공개 브리핑 · 무료
          </p>
        </div>
      </section>

      {(brief.sovereignIndex ?? brief.riskOverlay) && (
        <SovereignLiveStrip
          sovereignIndex={brief.sovereignIndex}
          riskOverlay={brief.riskOverlay}
          latestDate={latestDate}
        />
      )}

      <Divider />

      <section id="about" className="relative z-10 flex min-h-dvh flex-col justify-center px-6 py-14 md:px-20 md:py-24">
        <SectionHeading
          label="WHAT WE DO"
          title={
            <>
              뉴스를 전달하지 않습니다.
              <br />
              판단의 방향을 정리합니다.
            </>
          }
        />
        <div className="mt-9 flex flex-col gap-4 md:mt-18 md:flex-row md:gap-6">
          {operatingPrinciples.map((item) => (
            <article key={item.num} className="flex-1 rounded-md border border-[rgba(169,146,125,0.12)] p-7 md:p-9">
              <div className="flex items-center gap-4 md:block">
                <span className="text-[32px] font-light leading-none text-[var(--accent-primary)] md:text-5xl">
                  {item.num}
                </span>
                <span className="text-base font-semibold text-[var(--smoke)] md:hidden">{item.title}</span>
              </div>
              <h3 className="mt-5 hidden text-xl font-semibold text-[var(--smoke)] md:block">{item.title}</h3>
              <p className="mt-3.5 text-sm leading-relaxed text-[var(--taupe)] md:mt-5 md:text-[15px]">{item.desc}</p>
            </article>
          ))}
        </div>
      </section>

      <Divider />

      <section className="relative z-10 flex min-h-dvh flex-col justify-center px-6 py-14 md:px-20 md:py-24">
        <SectionHeading
          label="WHY DIFFERENT"
          title={
            <>
              같은 데이터를 읽어도
              <br />
              결론은 달라질 수 있습니다.
            </>
          }
        />
        <div className="mt-9 flex flex-col gap-4 md:mt-16 md:flex-row md:gap-0">
          <ComparisonPanel title="일반 뉴스 서비스" rows={comparisonRows.common} muted />
          <ComparisonPanel title="SOVEREIGN BRIEF" rows={comparisonRows.sovereign} />
        </div>
      </section>

      <Divider />

      <section id="sample" className="relative z-10 flex min-h-dvh flex-col justify-center px-6 py-14 md:px-20 md:py-24">
        <SectionHeading label="TODAY'S BRIEF" title="이런 흐름으로 읽게 됩니다." />
        <article className="mt-8 rounded-lg border border-[rgba(169,146,125,0.15)] bg-[rgba(242,244,243,0.04)] p-6 md:mt-16 md:p-10">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-[10px] font-medium uppercase tracking-[0.12em] text-[var(--taupe)] md:text-[11px]">
                {brief.meta.date} · LIVE SNAPSHOT
              </p>
              <h2 className="mt-3 text-lg font-bold leading-snug text-[var(--smoke)] md:text-[26px]">
                {heroHeadline}
              </h2>
            </div>
            <Link
              href={`/archive/${latestDate}`}
              className="inline-flex w-fit items-center gap-2 rounded-md bg-[var(--accent-primary)] px-5 py-3 text-[15px] font-semibold text-[var(--smoke)] transition-colors hover:bg-[var(--accent-primary-strong)]"
            >
              오늘 브리프 먼저 읽기
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>

          <div className="my-6 h-px w-full bg-[rgba(169,146,125,0.10)]" />

          <div className="grid gap-3 md:grid-cols-4">
            {marketItems.map((item) => (
              <div key={item.symbol} className="rounded-md border border-[rgba(169,146,125,0.08)] bg-[rgba(242,244,243,0.03)] px-4 py-3">
                <div className="flex items-baseline gap-2">
                  <span className="numeric-md font-semibold text-[var(--smoke)]">{item.symbol}</span>
                  <span className={`numeric-sm font-medium ${
                    item.trend === "up"
                      ? "text-[var(--accent-green)]"
                      : item.trend === "down"
                        ? "text-[var(--accent-down)]"
                        : "text-white/50"
                  }`}>
                    {item.change ?? "N/A"}
                  </span>
                </div>
                <p className="numeric-sm mt-1 text-[var(--taupe)]/60">{item.label} · {item.value ?? "N/A"}</p>
              </div>
            ))}
          </div>

          {featuredNews.length > 0 ? (
            <>
              <div className="my-6 h-px w-full bg-[rgba(169,146,125,0.10)]" />
              <div className="space-y-3">
                <p className="text-[10px] font-medium uppercase tracking-[0.12em] text-[var(--taupe)] md:text-[11px]">
                  Narrative Inputs
                </p>
                {featuredNews.map((item) => (
                  <p key={`${item.source}-${item.title}`} className="text-[12px] leading-6 text-[var(--taupe)]/70">
                    <span className="font-semibold text-[var(--smoke)]">{item.source}</span> · {item.title}
                  </p>
                ))}
              </div>
            </>
          ) : null}
        </article>
      </section>
    </>
  );
}

function SectionHeading({ label, title }: { label: string; title: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-3 md:gap-4">
      <span className="text-[11px] font-medium uppercase tracking-[0.15em] text-[var(--accent-primary)] md:text-[13px]">
        {label}
      </span>
      <h2 className="text-[28px] font-bold leading-[1.36] text-[var(--smoke)] md:text-[44px] md:leading-[1.23]">
        {title}
      </h2>
    </div>
  );
}

function ComparisonPanel({
  title,
  rows,
  muted = false,
}: {
  title: string;
  rows: string[];
  muted?: boolean;
}) {
  return (
    <article
      className={`flex-1 rounded-md border p-7 md:p-10 ${
        muted
          ? "border-[rgba(169,146,125,0.08)] bg-[rgba(242,244,243,0.03)] md:rounded-r-none"
          : "border-[rgba(73,17,28,0.30)] bg-[rgba(73,17,28,0.12)] md:rounded-l-none"
      }`}
    >
      <h3 className={`text-[11px] font-semibold uppercase tracking-[0.10em] md:text-[13px] ${muted ? "text-[var(--taupe)]" : "text-[var(--smoke)]"}`}>
        {title}
      </h3>
      <div className="mt-5 flex flex-col gap-3">
        {rows.map((row) => (
          <div key={row} className="flex items-start gap-3">
            {muted ? (
              <span className="mt-0.5 shrink-0 text-sm text-[var(--taupe)]/36">—</span>
            ) : (
              <ArrowRight className="mt-0.5 h-4 w-4 shrink-0 text-[var(--accent-primary)]" aria-hidden />
            )}
            <span className={`text-sm leading-snug md:text-[15px] ${muted ? "text-[var(--taupe)]/60" : "font-medium text-[var(--smoke)]"}`}>
              {row}
            </span>
          </div>
        ))}
      </div>
    </article>
  );
}

function Divider() {
  return (
    <div className="relative z-10 px-6 py-2.5 md:px-20">
      <div className="h-px w-full bg-[rgba(169,146,125,0.12)]" />
    </div>
  );
}

/* ── zone helpers ───────────────────────────────────────────────────────── */

const ZONE_COLOR = { bull: "#10b981", neutral: "#64748b", bear: "#ef4444" } as const;
const ZONE_LABEL = { bull: "강세 구간", neutral: "중립 구간", bear: "약세 구간" } as const;

const REGIME_COLOR: Record<string, string> = {
  BullQuiet: "#10b981", BullHeated: "#f0b90b",
  BearPanic: "#ef4444", Choppy: "#f0b90b", Transitional: "rgba(255,255,255,0.72)",
};
const REGIME_LABEL: Record<string, string> = {
  BullQuiet: "안정 상승", BullHeated: "과열 상승",
  BearPanic: "공포 하락", Choppy: "방향 불명", Transitional: "전환 구간",
};

const CONF_COLOR: Record<string, string> = {
  HIGH: "#10b981", MEDIUM: "#f0b90b", LOW: "rgba(255,255,255,0.48)", NONE: "rgba(255,255,255,0.32)",
};
const CONF_LABEL: Record<string, string> = {
  HIGH: "신호 강함", MEDIUM: "신호 보통", LOW: "신호 약함", NONE: "대기",
};
const VOL_LABEL: Record<string, string> = { Low: "변동성 낮음", Mid: "변동성 보통", High: "변동성 높음" };

/* ── SovereignLiveStrip ─────────────────────────────────────────────────── */

function SovereignLiveStrip({
  sovereignIndex,
  riskOverlay,
  latestDate,
}: {
  sovereignIndex: SovereignIndex | null;
  riskOverlay: RiskOverlay | null;
  latestDate: string;
}) {
  const si = sovereignIndex;
  const ro = riskOverlay;

  return (
    <section className="relative z-10 px-6 py-8 md:px-20">
      <div className="mx-auto w-full max-w-6xl">
        {/* Label row */}
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span
              className="h-1.5 w-1.5 rounded-full bg-[#00ffff]"
              style={{ boxShadow: "0 0 5px rgba(0,255,255,0.6)" }}
            />
            <span className="font-mono text-[10px] uppercase tracking-[0.22em] text-[var(--taupe)]/50">
              Sovereign · 오늘의 주력 신호
            </span>
          </div>
          <span className="rounded-full border border-[rgba(0,255,255,0.18)] bg-[rgba(0,255,255,0.05)] px-2 py-0.5 font-mono text-[8px] uppercase tracking-[0.14em] text-[rgba(0,255,255,0.55)]">
            LIVE
          </span>
        </div>

        {/* Card */}
        <div
          className="relative overflow-hidden rounded-xl"
          style={{
            border: "1px solid rgba(0,255,255,0.10)",
            background: "linear-gradient(135deg, rgba(0,255,255,0.04), rgba(10,9,8,0.96) 50%, rgba(16,185,129,0.03))",
          }}
        >
          {/* top accent */}
          <div
            className="absolute inset-x-0 top-0 h-px"
            style={{ background: "linear-gradient(to right, transparent, rgba(0,255,255,0.30), rgba(16,185,129,0.14), transparent)" }}
          />

          <div className="grid gap-px bg-white/[0.04] md:grid-cols-2">

            {/* LEFT: Sovereign Index */}
            <div className="bg-[#0b0a08]/94 p-5 md:p-6">
              <div className="flex items-center gap-2 mb-4">
                <BarChart2 className="h-3.5 w-3.5" style={{ color: "#00ffff", opacity: 0.7 }} aria-hidden />
                <span className="font-mono text-[9px] uppercase tracking-[0.20em]" style={{ color: "#00ffff", opacity: 0.7 }}>
                  Sovereign Index
                </span>
              </div>

              {si ? (
                <div className="flex items-end gap-4">
                  {/* Score + delta */}
                  <div>
                    <div className="flex items-baseline gap-1.5">
                      <span
                        className="font-mono text-[52px] font-bold leading-none tabular-nums"
                        style={{ color: ZONE_COLOR[si.zone], letterSpacing: "-0.03em" }}
                      >
                        {Math.round(si.score)}
                      </span>
                      {si.scoreDelta != null && (
                        <span
                          className="font-mono text-[15px] font-semibold tabular-nums leading-none"
                          style={{ color: si.scoreDelta >= 0 ? "#10b981" : "#f87171" }}
                        >
                          {si.scoreDelta >= 0 ? "↑" : "↓"}{Math.abs(Math.round(si.scoreDelta))}
                        </span>
                      )}
                    </div>
                    <span className="font-mono text-sm text-white/30">/ 100</span>
                  </div>

                  {/* Zone + context + gauge */}
                  <div className="mb-1 flex-1">
                    <span className="text-sm font-bold" style={{ color: ZONE_COLOR[si.zone] }}>
                      {si.labelKo}
                    </span>
                    <p className="mt-0.5 font-mono text-[9px] uppercase tracking-[0.12em] text-white/30">
                      {ZONE_LABEL[si.zone]}
                    </p>
                    {si.scorePercentile != null && (
                      <p className="mt-0.5 font-mono text-[9px] text-white/24">
                        30일 중 상위 {100 - si.scorePercentile}%
                      </p>
                    )}
                    {/* Gauge bar */}
                    <div className="mt-2.5 h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${Math.min(100, Math.max(0, si.score))}%`,
                          background: ZONE_COLOR[si.zone],
                        }}
                      />
                    </div>
                  </div>
                </div>
              ) : (
                <p className="font-mono text-[11px] text-white/26">데이터 준비 중</p>
              )}
            </div>

            {/* RIGHT: Sovereign State */}
            <div className="bg-[#0b0a08]/94 p-5 md:p-6">
              <div className="flex items-center gap-2 mb-4">
                <Activity className="h-3.5 w-3.5 text-white/50" aria-hidden />
                <span className="font-mono text-[9px] uppercase tracking-[0.20em] text-white/50">
                  Sovereign State
                </span>
              </div>

              {ro ? (
                <div className="flex items-end justify-between gap-4">
                  {/* Regime */}
                  <div>
                    <span
                      className="text-[28px] font-black leading-none"
                      style={{ color: REGIME_COLOR[ro.regimeState] ?? "rgba(255,255,255,0.76)" }}
                    >
                      {REGIME_LABEL[ro.regimeState] ?? ro.regimeState}
                    </span>
                    <p className="mt-1 font-mono text-[9px] uppercase tracking-[0.16em] text-white/26">
                      {ro.regimeState}
                    </p>
                    {si?.regimeDurationDays != null && si.regimeDurationDays > 1 && (
                      <p className="mt-0.5 font-mono text-[9px] text-white/24">
                        {si.regimeDurationDays}일째 유지 중
                      </p>
                    )}
                  </div>

                  {/* Vol + signal pills */}
                  <div className="mb-1 flex flex-col items-end gap-1.5">
                    {ro.volLevel && (
                      <span className="rounded border border-white/8 bg-white/[0.04] px-2 py-0.5 font-mono text-[10px] text-white/46">
                        {VOL_LABEL[ro.volLevel] ?? ro.volLevel}
                      </span>
                    )}
                    {ro.signalConfidence && (
                      <span
                        className="rounded border px-2 py-0.5 font-mono text-[10px] font-semibold"
                        style={{
                          color: CONF_COLOR[ro.signalConfidence] ?? "rgba(255,255,255,0.46)",
                          borderColor: `${CONF_COLOR[ro.signalConfidence] ?? "rgba(255,255,255,0.1)"}33`,
                          background: `${CONF_COLOR[ro.signalConfidence] ?? "rgba(255,255,255,0.04)"}14`,
                        }}
                      >
                        {CONF_LABEL[ro.signalConfidence] ?? ro.signalConfidence}
                      </span>
                    )}
                  </div>
                </div>
              ) : (
                <p className="font-mono text-[11px] text-white/26">데이터 준비 중</p>
              )}
            </div>
          </div>

          {/* Footer CTA */}
          <div className="flex items-center justify-between border-t border-white/[0.05] bg-[#0b0a08]/94 px-5 py-3 md:px-6">
            <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-white/24">
              전체 분석 · Sovereign Analysis
            </span>
            <Link
              href={`/archive/${latestDate}`}
              className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-white/38 transition-colors hover:text-[rgba(0,255,255,0.65)]"
            >
              오늘 브리프 전체 읽기
              <ArrowRight className="h-3 w-3" aria-hidden />
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
