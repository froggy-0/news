import type { BitcoinSection } from "@schema/brief.types";

import { DataState } from "@/components/ui/DataState";
import { Reveal } from "@/components/ui/Reveal";

export function BitcoinPanel({ bitcoin }: { bitcoin: BitcoinSection }) {
  const etf = bitcoin.etf;
  return (
    <Reveal className="panel space-y-8 rounded-[32px] px-6 py-7 md:px-8">
      <div className="flex flex-col gap-4 border-b border-white/8 pb-6 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="section-title">비트코인과 ETF</p>
          <h2 className="display-headline mt-4 max-w-4xl text-[2.1rem] md:text-[3.2rem]">
            비트코인 현물과 ETF 수급 축을 같은 리듬으로 정리합니다.
          </h2>
        </div>
        <p className="hero-support max-w-sm">
          현물 가격, 심리 지표, 공식 ETF 보유 현황만 남기고 추정치 성격이 강한 보조 수치는 걷어냈습니다.
        </p>
      </div>

      <div className="grid gap-7 xl:grid-cols-[1.1fr_0.9fr]">
        <div className="grid gap-4 md:grid-cols-[1.2fr_0.8fr]">
          <div className="panel-soft rounded-[26px] px-5 py-6">
            <div className="flex items-center justify-between gap-4">
              <p className="section-title">비트코인 현물</p>
              {bitcoin.change ? <span className="ticker-pill numeric">{bitcoin.change}</span> : null}
            </div>
            {bitcoin.price ? (
              <p className="numeric mt-5 text-[2.35rem] font-semibold tracking-[-0.04em] text-[var(--text-primary)] md:text-[3.3rem]">
                {bitcoin.price}
              </p>
            ) : (
              <div className="mt-5">
                <DataState message="이번 집계에서는 비트코인 현물을 확인하지 못했어요." />
              </div>
            )}
            <div className="divider mt-6" />
            <p className="copy-block mt-6">
              비트코인 축은 가격과 변동성만이 아니라 ETF 집행 강도와 위험 선호 변화까지 함께 읽을 때 해석이 안정됩니다.
            </p>
          </div>

          <div className="panel-soft rounded-[26px] px-5 py-6">
            <p className="section-title">공포탐욕</p>
            {bitcoin.fearGreedIndex ? (
              <>
                <div className="mt-5 flex items-end gap-3">
                  <p className="numeric text-[3.1rem] font-semibold tracking-[-0.05em] text-[var(--text-primary)] md:text-[3.55rem]">
                    {bitcoin.fearGreedIndex.value}
                  </p>
                  <span className="numeric pb-2 text-sm tracking-[0.18em] text-[var(--text-muted)] uppercase">/100</span>
                </div>
                <p className="mt-3 font-mono text-[11px] tracking-[0.28em] text-[var(--accent-primary)] uppercase">
                  {bitcoin.fearGreedIndex.label}
                </p>
                <div className="mt-6 h-[2px] w-full overflow-hidden rounded-full bg-white/8">
                  <div
                    className="h-full bg-[var(--accent-primary)] transition-all"
                    style={{ width: `${Math.max(8, Math.min(100, bitcoin.fearGreedIndex.value))}%` }}
                  />
                </div>
              </>
            ) : (
              <div className="mt-5">
                <DataState message="이번 집계에서는 공포탐욕지수를 확인하지 못했어요." />
              </div>
            )}
          </div>
        </div>

        <div className="panel-soft rounded-[26px] px-5 py-6">
          <div className="border-b border-white/8 pb-5">
            <div>
              <p className="section-title">공식 ETF 스냅샷</p>
              <p className="hero-support mt-3 max-w-md">
                공식 페이지에서 바로 확인되는 총 보유량과 총 AUM만 남겼고, stale 추정 수치나 환산치는 사용자 화면에서 뺐습니다.
              </p>
            </div>
            {etf ? (
              <div className="mt-5 grid gap-3 lg:grid-cols-2">
                <div className="rounded-[18px] border border-white/8 bg-black/30 px-4 py-3">
                  <p className="section-title">총 보유량</p>
                  {etf.totalHolding ? (
                    <p className="numeric mt-3 break-words text-sm leading-6 text-[var(--text-primary)] md:text-base">
                      {etf.totalHolding}
                    </p>
                  ) : null}
                </div>
                <div className="rounded-[18px] border border-white/8 bg-black/30 px-4 py-3">
                  <p className="section-title">총 AUM</p>
                  {etf.totalAum ? (
                    <p className="numeric mt-3 break-words text-sm leading-6 text-[var(--text-primary)] md:text-base">
                      {etf.totalAum}
                    </p>
                  ) : null}
                </div>
              </div>
            ) : null}
          </div>

          {etf ? (
            etf.issuers.length > 0 ? (
              <div className="mt-6 overflow-hidden rounded-[22px] border border-white/8 bg-black/20">
                <div className="grid grid-cols-[0.75fr_1fr_1fr] gap-3 border-b border-white/8 px-4 py-3">
                  <p className="section-title">운용사</p>
                  <p className="section-title">보유량</p>
                  <p className="section-title text-right">AUM</p>
                </div>
                {etf.issuers.map((issuer) => {
                  const rowClassName =
                    "grid grid-cols-[0.75fr_1fr_1fr] gap-3 border-t border-white/8 px-4 py-4 first:border-t-0";

                  if (!issuer.sourceUrl) {
                    return (
                      <div key={issuer.name} className={rowClassName}>
                      <p className="font-mono text-[11px] tracking-[0.18em] text-[var(--text-primary)] uppercase">{issuer.name}</p>
                        <p className="numeric text-sm text-[var(--text-secondary)]">{issuer.holding}</p>
                        <p className="numeric text-right text-sm text-[var(--text-secondary)]">{issuer.aum}</p>
                      </div>
                    );
                  }

                  return (
                    <a
                      key={issuer.name}
                      href={issuer.sourceUrl}
                      target="_blank"
                      rel="noreferrer"
                      className={`${rowClassName} transition hover:bg-white/[0.04]`}
                    >
                      <p className="font-mono text-[11px] tracking-[0.18em] text-[var(--text-primary)] uppercase">{issuer.name}</p>
                      <p className="numeric text-sm text-[var(--text-secondary)]">{issuer.holding}</p>
                      <p className="numeric text-right text-sm text-[var(--text-secondary)]">{issuer.aum}</p>
                    </a>
                  );
                })}
              </div>
            ) : (
              <div className="mt-6">
                <DataState message="이번 집계에서는 ETF 발행사별 보유 현황을 확인하지 못했어요." />
              </div>
            )
          ) : (
            <div className="mt-6">
              <DataState message="이번 집계에서는 공식 ETF 보유 현황을 확인하지 못했어요." />
            </div>
          )}
        </div>
      </div>
    </Reveal>
  );
}
