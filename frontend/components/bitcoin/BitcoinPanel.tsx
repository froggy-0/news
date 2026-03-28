"use client";

import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";

import type { BitcoinSection } from "@schema/brief.types";

import { DataState } from "@/components/ui/DataState";

function compactBitcoinTone(kind: "bitcoin" | "fear" | "etf"): CSSProperties {
  if (kind === "bitcoin") {
    return {
      borderColor: "rgba(0,255,170,0.3)",
      background: "linear-gradient(135deg, rgba(0,255,170,0.16), rgba(6,20,18,0.96) 82%)",
    };
  }

  if (kind === "fear") {
    return {
      borderColor: "rgba(0,255,255,0.26)",
      background: "linear-gradient(135deg, rgba(0,255,255,0.14), rgba(8,16,24,0.96) 82%)",
    };
  }

  return {
    borderColor: "rgba(255,255,255,0.12)",
    background: "linear-gradient(135deg, rgba(255,255,255,0.08), rgba(10,10,10,0.96) 82%)",
  };
}

function trendFromChange(change: string | null | undefined): "up" | "down" | "neutral" {
  if (!change) {
    return "neutral";
  }

  if (change.includes("-")) {
    return "down";
  }

  if (change.includes("+")) {
    return "up";
  }

  return "neutral";
}

function bitcoinCardDelayFor(index: number): string {
  if (index === 0) return "160ms";
  if (index === 1) return "620ms";
  if (index === 2) return "920ms";
  return "1140ms";
}

export function BitcoinPanel({
  bitcoin,
  variant = "detail",
}: {
  bitcoin: BitcoinSection;
  variant?: "home" | "detail";
}) {
  const sectionRef = useRef<HTMLElement | null>(null);
  const [cardsActivated, setCardsActivated] = useState(false);
  const etf = bitcoin.etf;
  const compactHome = variant === "home";

  useEffect(() => {
    if (!compactHome) {
      return;
    }

    const node = sectionRef.current;
    if (!node || cardsActivated) {
      return;
    }

    let activationTimer: ReturnType<typeof setTimeout> | null = null;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          activationTimer = setTimeout(() => {
            setCardsActivated(true);
          }, 220);
          observer.disconnect();
        }
      },
      { threshold: 0.38 },
    );

    observer.observe(node);
    return () => {
      observer.disconnect();
      if (activationTimer) {
        clearTimeout(activationTimer);
      }
    };
  }, [cardsActivated, compactHome]);

  return (
    <section ref={sectionRef} className="border-b border-white/10 px-6 py-16">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div className="space-y-1">
            <p className="section-title">비트코인과 ETF</p>
            <p className="max-w-2xl text-sm leading-6 text-white/62">
              현물 가격, 투자 심리, 공식 ETF 핵심 수치를 압축해서 함께 봅니다.
            </p>
          </div>
          {variant === "detail" ? (
            <p className="max-w-md text-sm leading-7 text-white/52">
              시세와 심리만 따로 보지 않고, 실제 ETF 집행 강도와 함께 읽도록 구성합니다.
            </p>
          ) : null}
        </div>

        {compactHome ? (
          bitcoin.price || bitcoin.fearGreedIndex || etf ? (
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {bitcoin.price ? (
                <div
                  className={cardsActivated ? "card-data market-heat-card market-heat-card--active" : "card-data market-heat-card"}
                  data-trend={trendFromChange(bitcoin.change)}
                  style={{ animationDelay: bitcoinCardDelayFor(0) }}
                >
                  <div className="border px-3 py-2.5" style={compactBitcoinTone("bitcoin")}>
                    <p className="section-title">비트코인 현물</p>
                    <div className="mt-2 flex items-center justify-between gap-3">
                      <p className="numeric text-base text-white">{bitcoin.price}</p>
                      <p className="text-[9px] font-mono text-[#00ffff]">{bitcoin.change ?? "보합"}</p>
                    </div>
                  </div>
                </div>
              ) : null}

              {bitcoin.fearGreedIndex ? (
                <div
                  className={cardsActivated ? "card-data market-heat-card market-heat-card--active" : "card-data market-heat-card"}
                  data-trend="neutral"
                  style={{ animationDelay: bitcoinCardDelayFor(1) }}
                >
                  <div className="border px-3 py-2.5" style={compactBitcoinTone("fear")}>
                    <p className="section-title">공포탐욕</p>
                    <div className="mt-2 flex items-center justify-between gap-3">
                      <p className="numeric text-base text-white">{bitcoin.fearGreedIndex.value}/100</p>
                      <p className="text-[9px] font-mono text-[#00ffff]">{bitcoin.fearGreedIndex.label}</p>
                    </div>
                  </div>
                </div>
              ) : null}

              {etf?.totalHolding ? (
                <div
                  className={cardsActivated ? "card-data market-heat-card market-heat-card--active" : "card-data market-heat-card"}
                  data-trend="neutral"
                  style={{ animationDelay: bitcoinCardDelayFor(2) }}
                >
                  <div className="border px-3 py-2.5" style={compactBitcoinTone("etf")}>
                    <p className="section-title">ETF 총 보유량</p>
                    <div className="mt-2">
                      <p className="numeric text-base text-white">{etf.totalHolding}</p>
                    </div>
                  </div>
                </div>
              ) : null}

              {etf?.totalAum ? (
                <div
                  className={cardsActivated ? "card-data market-heat-card market-heat-card--active" : "card-data market-heat-card"}
                  data-trend="neutral"
                  style={{ animationDelay: bitcoinCardDelayFor(3) }}
                >
                  <div className="border px-3 py-2.5" style={compactBitcoinTone("etf")}>
                    <p className="section-title">ETF 총 AUM</p>
                    <div className="mt-2">
                      <p className="numeric text-base text-white">{etf.totalAum}</p>
                    </div>
                  </div>
                </div>
              ) : null}
            </div>
          ) : (
            <DataState message="이번 집계에서는 비트코인 및 ETF 수치를 확인하지 못했어요." />
          )
        ) : (
          <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
            <div className="grid gap-4 md:grid-cols-[1.1fr_0.9fr]">
              <div className="section-shell rounded-[28px] p-6">
                <div className="flex items-center justify-between gap-4">
                  <p className="section-title">비트코인 현물</p>
                  {bitcoin.change ? <span className="ticker-pill numeric">{bitcoin.change}</span> : null}
                </div>
                {bitcoin.price ? (
                  <p className="numeric mt-5 text-[2.3rem] tracking-[-0.05em] text-white md:text-[3rem]">
                    {bitcoin.price}
                  </p>
                ) : (
                  <div className="mt-5">
                    <DataState message="이번 집계에서는 비트코인 현물을 확인하지 못했어요." />
                  </div>
                )}
                <div className="mt-6 border-t border-white/8 pt-6">
                  <p className="text-sm leading-7 text-white/58">
                    가격만으로는 방향을 단정하지 않고, 위험 선호와 ETF 수급의 동시 변화를 함께 해석합니다.
                  </p>
                </div>
              </div>

              <div className="section-shell rounded-[28px] p-6">
                <p className="section-title">공포탐욕</p>
                {bitcoin.fearGreedIndex ? (
                  <>
                    <div className="mt-5 flex items-end gap-3">
                      <p className="numeric text-[3rem] tracking-[-0.05em] text-white">
                        {bitcoin.fearGreedIndex.value}
                      </p>
                      <span className="numeric pb-2 text-sm uppercase tracking-[0.18em] text-white/32">/100</span>
                    </div>
                    <p className="mt-3 text-[11px] font-mono uppercase tracking-[0.22em] text-[#00ffff]">
                      {bitcoin.fearGreedIndex.label}
                    </p>
                    <div className="mt-6 h-[3px] overflow-hidden rounded-full bg-white/10">
                      <div
                        className="h-full bg-[#00ffff]"
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

            <div className="section-shell rounded-[28px] p-6">
              <div className="border-b border-white/8 pb-5">
                <p className="section-title">공식 ETF 스냅샷</p>
                <p className="mt-3 max-w-md text-sm leading-7 text-white/58">
                  공식 페이지에서 바로 확인되는 총 보유량과 총 AUM만 남기고, 추정성 강한 수치는 제거합니다.
                </p>
                {etf ? (
                  <div className="mt-5 grid gap-3 md:grid-cols-2">
                    <StatBlock label="총 보유량" value={etf.totalHolding} />
                    <StatBlock label="총 AUM" value={etf.totalAum} />
                  </div>
                ) : null}
              </div>

              {etf ? (
                etf.issuers.length > 0 ? (
                  <div className="mt-6 overflow-hidden rounded-[22px] border border-white/8 bg-black/25">
                    <div className="grid grid-cols-[0.7fr_1fr_1fr] gap-3 border-b border-white/8 px-4 py-3">
                      <p className="section-title">운용사</p>
                      <p className="section-title">보유량</p>
                      <p className="section-title text-right">AUM</p>
                    </div>
                    {etf.issuers.map((issuer) =>
                      issuer.sourceUrl ? (
                        <a
                          key={issuer.name}
                          href={issuer.sourceUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="grid grid-cols-[0.7fr_1fr_1fr] gap-3 border-t border-white/8 px-4 py-4 transition first:border-t-0 hover:bg-white/[0.04]"
                        >
                          <p className="text-[11px] font-mono uppercase tracking-[0.18em] text-white">{issuer.name}</p>
                          <p className="numeric text-sm text-white/70">{issuer.holding ?? "N/A"}</p>
                          <p className="numeric text-right text-sm text-white/70">{issuer.aum ?? "N/A"}</p>
                        </a>
                      ) : (
                        <div
                          key={issuer.name}
                          className="grid grid-cols-[0.7fr_1fr_1fr] gap-3 border-t border-white/8 px-4 py-4 first:border-t-0"
                        >
                          <p className="text-[11px] font-mono uppercase tracking-[0.18em] text-white">{issuer.name}</p>
                          <p className="numeric text-sm text-white/70">{issuer.holding ?? "N/A"}</p>
                          <p className="numeric text-right text-sm text-white/70">{issuer.aum ?? "N/A"}</p>
                        </div>
                      ),
                    )}
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
        )}
      </div>
    </section>
  );
}

function StatBlock({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="rounded-[18px] border border-white/8 bg-black/35 px-4 py-4">
      <p className="section-title">{label}</p>
      <p className="numeric mt-3 break-words text-sm leading-6 text-white">{value ?? "N/A"}</p>
    </div>
  );
}
