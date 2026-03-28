"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, Calendar, Menu, X } from "lucide-react";
import clsx from "clsx";

import type { DrawerStatusCard, HistoryMenuEntry } from "@/lib/history";

export function HistoryDrawerClient({
  entries,
  statusCards,
  currentDate,
  initialVisibleCount = 4,
}: {
  entries: HistoryMenuEntry[];
  statusCards: DrawerStatusCard[];
  currentDate?: string;
  initialVisibleCount?: number;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [visibleCount, setVisibleCount] = useState(initialVisibleCount);
  const drawerRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const lastActiveElementRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const previousOverflow = document.body.style.overflow;
    const activeElement = document.activeElement;
    if (activeElement instanceof HTMLElement) {
      lastActiveElementRef.current = activeElement;
    }

    document.body.style.overflow = "hidden";

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsOpen(false);
        return;
      }

      if (event.key !== "Tab" || !drawerRef.current) {
        return;
      }

      const focusableElements = Array.from(
        drawerRef.current.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => !element.hasAttribute("disabled"));

      if (focusableElements.length === 0) {
        return;
      }

      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];
      const activeElement = document.activeElement;

      if (event.shiftKey && activeElement === firstElement) {
        event.preventDefault();
        lastElement?.focus();
      } else if (!event.shiftKey && activeElement === lastElement) {
        event.preventDefault();
        firstElement?.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
      lastActiveElementRef.current?.focus();
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    closeButtonRef.current?.focus();
  }, [isOpen]);

  return (
    <>
      <button
        type="button"
        onClick={() => setIsOpen(true)}
        className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-white/10 text-white/70 transition hover:border-white/25 hover:text-white"
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        aria-controls="history-drawer"
        aria-label="히스토리 메뉴 열기"
      >
        <Menu className="h-5 w-5" />
      </button>

      <AnimatePresence>
        {isOpen ? (
          <>
            <motion.div
              className="fixed inset-0 z-[90] bg-black/70 backdrop-blur-sm"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setIsOpen(false)}
            />
            <motion.aside
              id="history-drawer"
              ref={drawerRef}
              role="dialog"
              aria-modal="true"
              aria-label="브리프 히스토리 메뉴"
              className="fixed inset-y-0 right-0 z-[100] flex w-full max-w-[420px] flex-col border-l border-white/10 bg-black/95 px-6 py-7 shadow-[0_0_80px_rgba(0,0,0,0.6)] backdrop-blur-xl md:px-8"
              initial={{ x: "100%" }}
              animate={{ x: 0 }}
              exit={{ x: "100%" }}
              transition={{ type: "spring", damping: 28, stiffness: 220 }}
            >
              <div className="mb-10 flex items-center justify-between gap-4">
                <div>
                  <p className="text-[10px] font-mono uppercase tracking-[0.36em] text-white/35">Archive Index</p>
                  <p className="mt-2 text-sm tracking-tight text-white/60">
                    저장된 발행본을 같은 정적 경로로 다시 엽니다.
                  </p>
                </div>
                <button
                  ref={closeButtonRef}
                  type="button"
                  onClick={() => setIsOpen(false)}
                  className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-white/10 text-white/55 transition hover:border-white/25 hover:text-white"
                  aria-label="히스토리 메뉴 닫기"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              <div className="flex-1 overflow-y-auto pr-1">
                <div className="space-y-4">
                  <div className="space-y-2">
                    <p className="text-[10px] font-mono uppercase tracking-[0.3em] text-[#00ffff]">Daily Intelligence Briefs</p>
                    <div className="grid gap-2">
                      {entries.slice(0, visibleCount).map((entry) => (
                        <Link
                          key={entry.date}
                          href={entry.href}
                          className={clsx(
                            "group flex items-center justify-between rounded-2xl border px-4 py-4 transition-all duration-300",
                            entry.isCurrent
                              ? "border-[#00ffff]/40 bg-[#00ffff]/10 text-[#00ffff]"
                              : "border-white/8 bg-white/[0.02] text-white/65 hover:border-white/18 hover:bg-white/[0.05] hover:text-white",
                          )}
                          onClick={() => setIsOpen(false)}
                        >
                          <div className="flex items-center gap-3">
                            <div
                              className={clsx(
                                "flex h-9 w-9 items-center justify-center rounded-full border",
                                entry.isCurrent ? "border-[#00ffff]/35 bg-[#00ffff]/10" : "border-white/10 bg-white/[0.03]",
                              )}
                            >
                              <Calendar className="h-4 w-4" />
                            </div>
                            <div className="space-y-1">
                              <p className="font-mono text-sm tracking-tight">{entry.date}</p>
                              <p className="text-[10px] font-mono uppercase tracking-[0.2em] text-white/35">
                                {entry.isCurrent ? "현재 발행본" : "정적 아카이브"}
                              </p>
                            </div>
                          </div>
                          <ArrowRight
                            className={clsx(
                              "h-4 w-4 transition-transform duration-200",
                              entry.isCurrent ? "opacity-100" : "opacity-0 group-hover:translate-x-1 group-hover:opacity-100",
                            )}
                          />
                        </Link>
                      ))}
                    </div>
                    {visibleCount < entries.length ? (
                      <button
                        type="button"
                        onClick={() => setVisibleCount((count) => count + 6)}
                        className="mt-2 w-full rounded-2xl border border-dashed border-white/12 px-4 py-4 text-[10px] font-mono uppercase tracking-[0.24em] text-white/35 transition hover:border-white/22 hover:bg-white/[0.03] hover:text-white/70"
                      >
                        Load More Archive
                      </button>
                    ) : null}
                  </div>

                  <div className="border-t border-white/6 pt-7">
                    <div className="mb-4 flex items-center justify-between gap-4">
                      <p className="text-[10px] font-mono uppercase tracking-[0.3em] text-white/30">System Status</p>
                      {currentDate ? (
                        <span className="rounded-full border border-white/10 px-3 py-1 text-[9px] font-mono uppercase tracking-[0.2em] text-white/45">
                          {currentDate}
                        </span>
                      ) : null}
                    </div>
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                      {statusCards.map((card) => (
                        <div key={card.label} className="rounded-2xl border border-white/8 bg-white/[0.02] p-4">
                          <p className="text-[9px] font-mono uppercase tracking-[0.24em] text-white/28">{card.label}</p>
                          <p
                            className={clsx(
                              "mt-2 text-xs font-mono leading-5",
                              card.tone === "positive" && "text-[#00ffff]",
                              card.tone === "warning" && "text-[#ffd166]",
                              (!card.tone || card.tone === "muted") && "text-white/72",
                            )}
                          >
                            {card.value}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </motion.aside>
          </>
        ) : null}
      </AnimatePresence>
    </>
  );
}
