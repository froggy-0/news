import type { BriefData } from "@schema/brief.types";

import { SubscriptionForm } from "@/components/layout/SubscriptionForm";

import { ScatterText } from "./ScatterText";
import { TerminalPanel } from "./TerminalPanel";

export function HomeHero({ brief }: { brief: BriefData }) {
  return (
    <section className="hero-stage">
      <div className="mx-auto w-full max-w-4xl px-6">
        <div className="space-y-10">
          <div className="space-y-6">
            <div className="inline-flex items-center gap-3 rounded-full border border-white/10 bg-white/[0.02] px-4 py-2">
              <span className="h-1.5 w-1.5 rounded-full bg-[#00ff66] shadow-[0_0_10px_rgba(0,255,102,0.65)]" />
              <span className="text-[10px] font-mono uppercase tracking-[0.32em] text-white/50">오늘 발행본</span>
            </div>
            <h1 className="text-[1.75rem] font-black leading-[1.05] tracking-[-0.08em] text-white md:text-[3.4rem]">
              <span>주권 있는</span>
              <br />
              <span>투자자를 위한</span>
              <br />
              <ScatterText text="데이터 인텔리전스" fontSize={58} />
            </h1>
            <p className="max-w-[90%] text-sm leading-relaxed tracking-tight text-white/62 md:text-base">
              글로벌 마켓 데이터의 정교한 연결,
              <br />
              원본의 무결성으로 완성하는 투자 주권.
            </p>
          </div>

          <div className="max-w-md">
            <SubscriptionForm />
          </div>

          <div className="pt-6">
            <TerminalPanel meta={brief.meta} />
          </div>
        </div>
      </div>
    </section>
  );
}
