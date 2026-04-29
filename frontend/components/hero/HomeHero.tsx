import Link from "next/link";
import { ArrowRight } from "lucide-react";
import React from "react";
import type { BriefData } from "@schema/brief.types";

import { SubscriptionForm } from "@/components/layout/SubscriptionForm";
import { displayHeadline, formatPublicationDate, hasUsableHeadline } from "@/lib/format";

const operatingPrinciples = [
  {
    num: "01",
    title: "기관 프레이밍 감지",
    desc: "뉴스의 속도보다 월가가 어떤 언어로 시장을 해석하기 시작했는지를 먼저 봅니다.",
  },
  {
    num: "02",
    title: "가격 신호 교차 확인",
    desc: "금리, 달러, 변동성, 비트코인, 기술주가 같은 방향을 가리키는지 함께 점검합니다.",
  },
  {
    num: "03",
    title: "브리프 형성 예측",
    desc: "흩어진 데이터를 하나의 판단으로 묶어 다음 거래일 전에 읽을 수 있게 정리합니다.",
  },
];

const comparisonRows = {
  common: ["속보와 팩트 나열", "단일 뉴스 흐름 중심", "내러티브 형성 이후 해석", "모든 신호를 같은 무게로 취급"],
  sovereign: [
    "탑티어 기관의 분석/전망/프레이밍 추적",
    "복수 소스 수렴 + 가격 신호 교차 검증",
    "시장 내러티브 형성 이전에 판단",
    "노이즈 엄격 필터링, 침묵도 신호로 처리",
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
          <p className="text-[11px] font-medium uppercase tracking-[0.15em] text-[var(--accent-primary)] md:text-[13px]">
            WALL STREET NARRATIVE INTELLIGENCE
          </p>

          <h1 className="mt-6 text-4xl font-bold leading-[1.15] text-[var(--smoke)] md:mt-8 md:text-7xl md:leading-[1.14]">
            SOVEREIGN BRIEF
          </h1>
          <p className="mt-3 text-4xl font-bold leading-[1.15] text-[var(--taupe)] md:text-7xl md:leading-[1.14]">
            시장이 움직이기 전에.
          </p>

          <p className="mt-7 max-w-xs break-keep text-[15px] leading-relaxed text-[var(--taupe)] md:mt-10 md:max-w-[560px] md:text-lg">
            Goldman, Morgan Stanley, Bloomberg 흐름과 시장 데이터를 함께 스캔해 내러티브가 가격에 반영되기 전에 읽습니다.
          </p>

          <div id="subscribe" className="mt-14 w-full max-w-md md:mt-16 md:max-w-[520px]">
            <SubscriptionForm />
          </div>
          <p className="mt-4 text-xs text-[var(--taupe)]/45 md:text-[13px]">
            매일 아침 · 공개 브리핑 · 무료 구독
          </p>
        </div>
      </section>

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
                  <span className="numeric-sm font-semibold text-[var(--smoke)]">{item.symbol}</span>
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
                <p className="numeric-sm mt-1 text-[10px] text-[var(--taupe)]/60">{item.label} · {item.value ?? "N/A"}</p>
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
            <span className={`text-sm ${muted ? "text-[var(--taupe)]/40" : "text-[var(--accent-primary)]"}`}>
              {muted ? "-" : "->"}
            </span>
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
