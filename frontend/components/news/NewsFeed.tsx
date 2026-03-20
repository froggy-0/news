"use client";

import { motion } from "motion/react";

import type { NewsItem } from "@schema/brief.types";

import { DataState } from "@/components/ui/DataState";
import { formatRelativeTime } from "@/lib/format";

function urgencyLabel(value: NewsItem["urgency"]): string {
  if (value === "high") {
    return "높음";
  }
  if (value === "medium") {
    return "보통";
  }
  return "낮음";
}

function categoryLabel(value: NewsItem["category"]): string {
  if (value === "macro") return "거시";
  if (value === "bigtech") return "빅테크";
  if (value === "bitcoin") return "비트코인";
  return "미국 증시";
}

export function NewsFeed({ items }: { items: NewsItem[] }) {
  return (
    <section className="section-shell rounded-[8px] px-5 py-6 md:px-8 md:py-8">
      <div className="mb-8 flex flex-col gap-3 border-b border-white/10 pb-6 md:flex-row md:items-end md:justify-between">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-[var(--accent-primary)]" />
            <p className="section-title">핵심 뉴스</p>
          </div>
          <h3 className="serif-display text-4xl italic tracking-[-0.04em] text-[var(--text-primary)] md:text-5xl">
            오늘의 시그널
          </h3>
        </div>
        <p className="eyebrow">실제 수집한 뉴스만 연결합니다</p>
      </div>
      {items.length === 0 ? (
        <DataState message="이번 집계에서는 주요 뉴스를 확인하지 못했어요." />
      ) : (
        <div className="divide-y divide-white/8">
          {items.map((item, index) => (
            <motion.article
              key={item.id}
              initial={{ opacity: 0, y: 18 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ duration: 0.5, delay: index * 0.06 }}
              className="group px-1 py-8 transition-colors hover:bg-white/[0.02] md:px-3 md:py-10"
            >
              <div className="flex flex-col gap-6 md:flex-row md:gap-10">
                <div className="md:w-32 md:shrink-0">
                  <div className="flex flex-wrap items-center gap-2 md:flex-col md:items-start">
                    <span className="font-mono text-sm font-semibold text-[var(--accent-primary)]">
                      {formatRelativeTime(item.publishedAt)}
                    </span>
                    <span
                      className={`rounded-[4px] px-2 py-1 font-mono text-[9px] tracking-[0.18em] ${
                        item.urgency === "high"
                          ? "bg-red-500/20 text-[var(--accent-down)]"
                          : item.urgency === "medium"
                            ? "bg-[var(--accent-primary)]/12 text-[var(--accent-primary)]"
                            : "bg-white/6 text-[var(--text-secondary)]"
                      }`}
                    >
                      {urgencyLabel(item.urgency)}
                    </span>
                    <span className="font-mono text-[9px] tracking-[0.18em] text-[var(--text-muted)]">
                      {categoryLabel(item.category)}
                    </span>
                  </div>
                </div>

                <div className="flex-1 space-y-4">
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="font-mono text-[10px] tracking-[0.24em] text-[var(--accent-cyan)]">
                      {item.source}
                    </span>
                    {item.sourceTier === "tier1" ? (
                      <span className="rounded-[4px] border border-[var(--accent-gold)]/35 px-2 py-1 font-mono text-[9px] tracking-[0.18em] text-[var(--accent-gold)]">
                        핵심 출처
                      </span>
                    ) : null}
                  </div>

                  <a href={item.url} target="_blank" rel="noreferrer" className="block">
                    <h4 className="serif-display text-3xl leading-[1.18] tracking-[-0.03em] text-[var(--text-primary)] transition-colors group-hover:text-[var(--accent-primary)] md:text-5xl">
                      {item.title}
                    </h4>
                  </a>

                  <div className="border-l-2 border-[var(--accent-primary)]/30 bg-[var(--accent-primary)]/6 px-4 py-3">
                    <p className="font-mono text-[9px] tracking-[0.18em] text-[var(--accent-primary)]">
                      핵심 해석
                    </p>
                    <p className="mt-2 text-sm leading-7 text-[var(--text-secondary)]">
                      {item.interpretation ?? "이번 기사에서는 별도 시장 해석이 붙지 않았습니다."}
                    </p>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    {item.tags.map((tag) => (
                      <span
                        key={tag}
                        className="rounded-[999px] border border-white/8 px-3 py-1 font-mono text-[9px] tracking-[0.16em] text-[var(--text-muted)]"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </motion.article>
          ))}
        </div>
      )}
    </section>
  );
}
