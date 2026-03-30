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
  const items = allItems.length > 0 ? allItems : featuredItems;

  return (
    <section id="signals" className="border-b border-white/10 px-6 py-16">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-10">
        <div className="flex flex-col gap-4">
          <div className="flex items-start gap-3">
            <div className="rounded-full bg-white/6 p-2.5">
              <XIcon />
            </div>
            <div className="flex max-w-xl flex-col gap-1">
              <h2 className="section-title">실시간 X 시그널</h2>
              <span className="eyebrow">Fast-moving Commentary</span>
              <p className="pt-2 text-[15px] leading-7 text-white/66">
                기사보다 빠른 감도 변화와 시장 반응을 짧은 레이더 메모처럼 압축합니다.
              </p>
            </div>
          </div>
        </div>

        <XSignalsList
          items={items}
          emptyMessage="이번 집계에서는 공식 X 시그널을 확인하지 못했어요."
        />
      </div>
    </section>
  );
}
