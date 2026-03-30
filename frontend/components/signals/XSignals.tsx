import React from "react";
import type { XSignal } from "@schema/brief.types";

import { DataState } from "@/components/ui/DataState";

import { XSignalsClient } from "./XSignalsClient";
import { XSignalsList } from "./XSignalsList";

export function XSignals({
  featuredItems,
  allItems,
  variant = "home",
  showRawToggle = false,
}: {
  featuredItems: XSignal[] | null;
  allItems: XSignal[] | null;
  variant?: "home" | "detail";
  showRawToggle?: boolean;
}) {
  const featured = featuredItems ?? [];
  const all = allItems ?? [];

  if (featured.length === 0 && all.length === 0) {
    return (
      <section id="signals" className="border-b border-white/10 px-6 py-16">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-10">
          <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div className="space-y-1">
              <h2 className="section-title">{variant === "home" ? "실시간 X 시그널" : "전체 X 시그널"}</h2>
              <span className="eyebrow">
                {variant === "home" ? "Fast-moving Commentary" : "Full Signal Flow"}
              </span>
            </div>
          </div>
          <DataState
            title="X 시그널 상태"
            message={
              variant === "home"
                ? "이번 집계에서는 공식 X 시그널을 확인하지 못했어요."
                : "이번 집계에서는 전체 X 시그널을 확인하지 못했어요."
            }
            family="reading"
            minHeight={220}
          />
        </div>
      </section>
    );
  }

  if (variant === "home") {
    return <XSignalsClient featuredItems={featured} allItems={all} />;
  }

  return (
    <section id="signals" className="border-b border-white/10 px-6 py-16">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-10">
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div className="space-y-1">
            <h2 className="text-[11px] font-mono uppercase tracking-[0.4em] text-white/60">
              전체 X 시그널
            </h2>
            <span className="text-[9px] font-mono uppercase tracking-[0.26em] text-white/28">
              Full Signal Flow
            </span>
          </div>
          <p className="max-w-md text-sm leading-7 text-white/52">
            상세 페이지에서는 전체 시그널을 다시 읽고, 필요하면 원문 표현도 함께 확인할 수 있습니다.
          </p>
        </div>

        <XSignalsList
          items={all}
          showRawToggle={showRawToggle}
          emptyMessage="이번 집계에서는 전체 X 시그널을 확인하지 못했어요."
        />
      </div>
    </section>
  );
}
