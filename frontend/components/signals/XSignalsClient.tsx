"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

import type { XSignal } from "@schema/brief.types";

import { XSignalsList } from "./XSignalsList";

const XIcon = () => (
  <svg viewBox="0 0 24 24" className="h-4 w-4 text-white" fill="currentColor" aria-hidden="true">
    <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.134l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
  </svg>
);

export function XSignalsClient({
  featuredItems,
  allItems,
}: {
  featuredItems: XSignal[];
  allItems: XSignal[];
}) {
  const [showAll, setShowAll] = useState(featuredItems.length === 0);

  return (
    <section id="signals" className="border-b border-white/10 px-6 py-16">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-10">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="rounded-full bg-white/6 p-2">
              <XIcon />
            </div>
            <div className="flex flex-col">
              <h2 className="text-[11px] font-mono uppercase tracking-[0.4em] text-white/60">
                실시간 X 시그널
              </h2>
              <span className="text-[9px] font-mono uppercase tracking-[0.26em] text-white/28">
                Fast-moving Commentary
              </span>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowAll((value) => !value)}
            className="flex items-center gap-2 rounded-full border border-white/10 px-3 py-2 text-[10px] font-mono uppercase tracking-[0.22em] text-white/48 transition hover:border-white/24 hover:text-white"
          >
            {showAll ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            <span>{showAll ? "추천 시그널" : "전체 보기"}</span>
          </button>
        </div>

        <XSignalsList
          items={showAll ? allItems : featuredItems}
          emptyMessage="이번 집계에서는 공식 X 시그널을 확인하지 못했어요."
        />
      </div>
    </section>
  );
}
