import React from "react";
import type { BriefData } from "@schema/brief.types";

import { SubscriptionForm } from "@/components/layout/SubscriptionForm";
import { displayHeadline, formatPublicationDate, hasUsableHeadline } from "@/lib/format";

import { ScatterText } from "./ScatterText";
import { TerminalPanel } from "./TerminalPanel";

export function HomeHero({ brief, heroSeed }: { brief: BriefData; heroSeed: string }) {
  const heroHeadline = hasUsableHeadline(brief.meta.displayHeadline || brief.aiJudgment.headline)
    ? displayHeadline(brief.meta.displayHeadline || brief.aiJudgment.headline)
    : `${formatPublicationDate(brief.meta.date)} 브리프`;

  return (
    <section className="hero-stage" data-hero-seed={heroSeed}>
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-5 sm:px-6">
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1.08fr)_minmax(20rem,0.92fr)] lg:items-end">
          <div className="space-y-5">
            <div className="space-y-3">
              <p className="eyebrow">Daily Intelligence Brief</p>
              <h1 className="max-w-[12ch] text-[2rem] font-black leading-[1.04] tracking-[-0.07em] text-[var(--text-primary)] md:text-[3.4rem]">
                <span>주권 있는</span>
                <br />
                <span>투자자를 위한</span>
                <br />
                <ScatterText
                  text="데이터 인텔리전스"
                  seed={heroSeed}
                  fontSize={58}
                  density={0.72}
                  spread={0.28}
                  durationMs={920}
                />
              </h1>
              <p className="copy-block max-w-[36rem] text-[0.98rem] text-[var(--text-secondary)]">
                글로벌 마켓 데이터의 정교한 연결과 해석을 한 화면에서 먼저 읽고,
                <br className="hidden sm:block" />
                자세한 숫자와 뉴스 흐름으로 자연스럽게 내려가도록 설계했습니다.
              </p>
            </div>

            <div className="card-family-reading space-y-4 rounded-[var(--card-radius-reading)] p-[var(--card-padding-reading)]">
              <div className="space-y-2">
                <p className="section-title">오늘의 핵심 판단</p>
                <p className="max-w-[34rem] text-[1rem] leading-7 text-[var(--text-primary)] md:text-[1.05rem]">
                  {heroHeadline}
                </p>
                <p className="text-[0.84rem] leading-6 text-[var(--text-secondary)]">
                  발행 기준일 {brief.meta.date} 기준으로 가장 먼저 읽어야 할 브리프를 상단에서 바로 엽니다.
                </p>
              </div>

              <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
                <a href="#brief" className="hero-cta-primary">
                  오늘 브리프 먼저 읽기
                </a>
                <a href="#news" className="hero-cta-secondary">
                  뉴스 흐름 보기
                </a>
              </div>
            </div>
          </div>

          <div className="space-y-4 lg:pb-1">
            <div className="card-family-utility rounded-[var(--card-radius-utility)] p-[var(--card-padding-utility)]">
              <div className="mb-4 space-y-2">
                <p className="section-title">Brief Access</p>
                <p className="text-[0.92rem] leading-6 text-[var(--text-secondary)]">
                  무료 구독으로 다음 발행부터 같은 형식의 브리프를 이메일로 받습니다.
                </p>
              </div>
              <SubscriptionForm />
            </div>
          </div>
        </div>

        <div className="pt-1">
          <TerminalPanel meta={brief.meta} compact />
        </div>
      </div>
    </section>
  );
}
