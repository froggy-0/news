import React from "react";
import type { XSignal } from "@schema/brief.types";

import { DataState } from "@/components/ui/DataState";

import { XSignalsList } from "./XSignalsList";

export function XSignals({
  featuredItems,
  allItems,
  showRawToggle = false,
}: {
  featuredItems: XSignal[] | null;
  allItems: XSignal[] | null;
  showRawToggle?: boolean;
}) {
  const featured = featuredItems ?? [];
  const all = allItems ?? [];

  if (featured.length === 0 && all.length === 0) {
    return (
      <section id="signals" className="border-b border-white/10 px-6 py-20">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-10">
          <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div className="space-y-1">
              <h2 className="section-title">All X Signals</h2>
              <span className="eyebrow">Full Signal Flow</span>            </div>
          </div>
          <DataState
            title="X 시그널 상태"
            message="이번 집계에서는 전체 X 시그널을 확인하지 못했어요."
            family="reading"
            minHeight={220}
          />
        </div>
      </section>
    );
  }

  return (
    <section id="signals" className="border-b border-white/10 px-6 py-20">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-10">
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div className="space-y-1">
            <h2 className="section-title">All X Signals</h2>
            <span className="eyebrow">Full Signal Flow</span>
          </div>
          <p className="max-w-md text-sm leading-7 text-white/52">
            The detail page shows all signals — original source language included.
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
