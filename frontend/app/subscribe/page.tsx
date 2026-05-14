import type { Metadata } from "next";
import { CheckCircle2, BarChart2, Mail, Zap } from "lucide-react";

import { SiteHeader } from "@/components/layout/SiteHeader";
import { SubscriptionForm } from "@/components/layout/SubscriptionForm";

export const metadata: Metadata = {
  title: "무료 구독 — SOVEREIGN BRIEF",
  description: "매일 아침 BTC 시장 국면 분석과 Sovereign Index를 이메일로 받아보세요. 무료.",
};

const FEATURES = [
  { icon: BarChart2, text: "Sovereign Index — BTC 시장 복합 지표 (0~100)" },
  { icon: Zap,       text: "Risk Overlay — 국면 상태 실시간 추적" },
  { icon: Mail,      text: "매일 오전 발송 · 구독 해지 언제든 가능" },
];

const PROOF_ITEMS = [
  { value: "30+", label: "데이터 소스" },
  { value: "7일", label: "예측 검증 주기" },
  { value: "100%", label: "무료" },
];

export default function SubscribePage() {
  return (
    <>
      <SiteHeader variant="home" />
      <main className="min-h-[calc(100vh-80px)] px-4 pb-24 pt-20 md:px-8">
        <div className="mx-auto max-w-lg">
          {/* Header */}
          <div className="mb-10 text-center">
            <div
              className="mx-auto mb-5 inline-flex items-center gap-2 rounded-full border px-4 py-1.5 font-mono text-[10px] uppercase tracking-[0.20em]"
              style={{ color: "#f0b90b", borderColor: "rgba(240,185,11,0.24)", background: "rgba(240,185,11,0.06)" }}
            >
              <span
                className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#f0b90b]"
                style={{ boxShadow: "0 0 6px rgba(240,185,11,0.7)" }}
              />
              매일 오전 발송
            </div>
            <h1 className="text-[32px] font-black leading-tight text-white md:text-[40px]">
              시장이 움직이기 전에<br />
              <span style={{ color: "#f0b90b" }}>먼저 알아야 합니다.</span>
            </h1>
            <p className="mx-auto mt-4 max-w-sm text-[15px] leading-7 text-white/48">
              Bloomberg, Reuters 데이터와 BTC 온체인 지표를 종합해 매일 아침 브리핑합니다.
            </p>
          </div>

          {/* Stats */}
          <div className="mb-8 grid grid-cols-3 gap-3">
            {PROOF_ITEMS.map(({ value, label }) => (
              <div
                key={label}
                className="rounded-lg border border-white/[0.07] bg-white/[0.025] px-3 py-4 text-center"
              >
                <p className="font-mono text-[22px] font-bold text-white/88">{value}</p>
                <p className="mt-1 font-mono text-[9px] uppercase tracking-[0.12em] text-white/32">{label}</p>
              </div>
            ))}
          </div>

          {/* Form card */}
          <div
            className="relative overflow-hidden rounded-xl border p-6 md:p-8"
            style={{
              borderColor: "rgba(240,185,11,0.18)",
              background: "linear-gradient(135deg, rgba(240,185,11,0.05), rgba(10,9,8,0.98) 60%)",
            }}
          >
            {/* Top accent line */}
            <div
              className="absolute inset-x-0 top-0 h-px"
              style={{ background: "linear-gradient(to right, transparent, rgba(240,185,11,0.5), transparent)" }}
            />
            <p className="mb-5 font-mono text-[11px] uppercase tracking-[0.18em] text-white/36">
              무료로 시작하기
            </p>
            <SubscriptionForm />
          </div>

          {/* Feature list */}
          <ul className="mt-6 space-y-3">
            {FEATURES.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-center gap-3">
                <CheckCircle2 className="h-4 w-4 shrink-0 text-[#10b981]" aria-hidden />
                <span className="text-[13px] text-white/52">{text}</span>
              </li>
            ))}
          </ul>
        </div>
      </main>
    </>
  );
}
