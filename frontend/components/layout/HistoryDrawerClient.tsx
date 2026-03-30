"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, Calendar, Menu, X } from "lucide-react";
import clsx from "clsx";

import type { DrawerStatusCard, HistoryMenuEntry } from "@/lib/history";
import { formatPublicationDate } from "@/lib/format";

function parseArchiveDate(value: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return null;
  }

  return new Date(`${value}T09:00:00+09:00`);
}

function archiveRelativeLabel(date: string, currentDate?: string): string {
  if (!currentDate || currentDate === date) {
    return "현재 발행본";
  }

  const target = parseArchiveDate(date);
  const current = parseArchiveDate(currentDate);
  if (!target || !current) {
    return "지난 발행본";
  }

  const diffDays = Math.round((current.getTime() - target.getTime()) / 86400000);
  if (diffDays === 1) {
    return "어제 발행본";
  }
  if (diffDays === 2) {
    return "그제 발행본";
  }
  if (diffDays > 2) {
    return `${diffDays}일 전 발행본`;
  }
  return "지난 발행본";
}

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
  const [isPortalReady, setIsPortalReady] = useState(false);
  const drawerRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const lastActiveElementRef = useRef<HTMLElement | null>(null);
  const currentEntry = entries.find((entry) => entry.isCurrent);
  const archiveEntries = entries.filter((entry) => !entry.isCurrent);

  useEffect(() => {
    setIsPortalReady(true);
  }, []);

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

  const drawerLayer = (
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
                <p className="text-[10px] font-mono uppercase tracking-[0.3em] text-white/35">Brief Archive</p>
                <p className="mt-2 text-base font-semibold tracking-tight text-white">
                  지난 브리프를 날짜별로 다시 읽기
                </p>
                <p className="mt-2 max-w-[18rem] text-sm leading-6 text-white/60">
                  오늘 발행본은 그대로 두고, 어제와 이전 발행본을 빠르게 열 수 있습니다.
                </p>
              </div>
              <button
                ref={closeButtonRef}
                type="button"
                onClick={() => setIsOpen(false)}
                className="inline-flex h-11 w-11 items-center justify-center rounded-full border border-white/10 text-white/55 transition hover:border-white/25 hover:text-white"
                aria-label="히스토리 메뉴 닫기"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto pr-1">
              <div className="space-y-4">
                {currentEntry ? (
                  <div className="space-y-2">
                    <p className="label-meta text-[var(--accent-primary)]">지금 읽는 발행본</p>
                    <div className="card-family-reading rounded-[var(--card-radius-reading)] p-[var(--card-padding-reading)]">
                      <div className="flex items-start justify-between gap-4">
                        <div className="space-y-2">
                          <p className="text-base font-semibold tracking-tight text-white">
                            {formatPublicationDate(currentEntry.date)}
                          </p>
                          <p className="text-sm leading-6 text-white/62">
                            현재 보고 있는 브리프입니다. 같은 화면에서 최신 흐름을 계속 읽을 수 있습니다.
                          </p>
                        </div>
                        <span className="label-meta rounded-full border border-cyan-300/20 bg-cyan-300/10 px-3 py-1 text-[var(--accent-primary)]">
                          {archiveRelativeLabel(currentEntry.date, currentDate)}
                        </span>
                      </div>
                      <div className="mt-4 flex flex-wrap gap-2">
                        <span className="label-meta rounded-full border border-white/10 px-3 py-1 text-white/45">
                          {currentEntry.date}
                        </span>
                        <span className="label-meta rounded-full border border-white/10 px-3 py-1 text-white/45">
                          홈 기준 발행본
                        </span>
                      </div>
                    </div>
                  </div>
                ) : null}

                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-3">
                    <p className="label-meta text-white/46">지난 발행본</p>
                    <span className="label-meta text-white/30">{archiveEntries.length}개</span>
                  </div>
                  {archiveEntries.length > 0 ? (
                    <div className="grid gap-2">
                      {archiveEntries.slice(0, visibleCount).map((entry) => (
                        <Link
                          key={entry.date}
                          href={entry.href}
                          className="card-family-utility group flex items-center justify-between gap-4 rounded-[var(--card-radius-utility)] px-4 py-4 text-white/70 transition-all duration-300 hover:border-white/18 hover:bg-white/[0.05] hover:text-white"
                          onClick={() => setIsOpen(false)}
                        >
                          <div className="flex min-w-0 items-center gap-3">
                            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-white/10 bg-white/[0.03] text-white/45">
                              <Calendar className="h-4 w-4" />
                            </div>
                            <div className="min-w-0 space-y-1">
                              <p className="truncate text-[0.98rem] font-semibold tracking-tight text-white">
                                {formatPublicationDate(entry.date)}
                              </p>
                              <div className="flex flex-wrap items-center gap-2 text-xs leading-5 text-white/42">
                                <span>{archiveRelativeLabel(entry.date, currentDate)}</span>
                                <span className="h-1 w-1 rounded-full bg-white/18" />
                                <span>{entry.date}</span>
                              </div>
                            </div>
                          </div>
                          <div className="flex shrink-0 items-center gap-2 text-xs font-medium text-white/48 transition group-hover:text-white">
                            <span>다시 읽기</span>
                            <ArrowRight className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-1" />
                          </div>
                        </Link>
                      ))}
                    </div>
                  ) : (
                    <div className="card-family-utility rounded-[var(--card-radius-utility)] p-[var(--card-padding-utility)]">
                      <p className="text-sm leading-6 text-white/60">
                        아직 이전 발행본이 충분히 쌓이지 않았습니다. 다음 발행이 누적되면 이곳에서 바로 다시 열 수 있습니다.
                      </p>
                    </div>
                  )}
                  {visibleCount < archiveEntries.length ? (
                    <button
                      type="button"
                      onClick={() => setVisibleCount((count) => count + 6)}
                      className="label-meta mt-2 w-full rounded-[var(--card-radius-utility)] border border-dashed border-white/12 px-4 py-4 text-white/35 transition hover:border-white/22 hover:bg-white/[0.03] hover:text-white/70"
                    >
                      지난 발행본 더 보기
                    </button>
                  ) : null}
                  <Link
                    href="/archive"
                    className="card-family-utility group mt-2 flex items-center justify-between rounded-[var(--card-radius-utility)] px-4 py-4 text-white/70 transition-all duration-300 hover:border-white/18 hover:bg-white/[0.05] hover:text-white"
                    onClick={() => setIsOpen(false)}
                  >
                    <div className="space-y-1">
                      <p className="text-sm font-semibold tracking-tight text-white">전체 아카이브 보기</p>
                      <p className="text-xs leading-5 text-white/42">날짜별 발행본을 한 번에 훑고 원하는 날짜로 이동합니다.</p>
                    </div>
                    <ArrowRight className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-1" />
                  </Link>
                </div>

                <div className="border-t border-white/6 pt-7">
                  <div className="mb-4 flex items-center justify-between gap-4">
                    <p className="label-meta text-white/30">현재 발행 상태</p>
                    {currentDate ? (
                      <span className="label-meta rounded-full border border-white/10 px-3 py-1 text-white/45">
                        {currentDate}
                      </span>
                    ) : null}
                  </div>
                  <div className="grid grid-cols-1 gap-3">
                    {statusCards.map((card) => (
                      <div
                        key={card.label}
                        className="card-family-utility flex items-center justify-between gap-4 rounded-[var(--card-radius-utility)] p-4"
                      >
                        <p className="label-meta text-white/28">{card.label}</p>
                        <p
                          className={clsx(
                            "text-right text-sm leading-6",
                            card.tone === "positive" && "text-[var(--status-positive)]",
                            card.tone === "warning" && "text-[var(--status-warning)]",
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
  );

  return (
    <>
      <button
        type="button"
        onClick={() => setIsOpen(true)}
        className="inline-flex h-11 w-11 items-center justify-center rounded-full border border-white/10 text-white/70 transition hover:border-white/25 hover:text-white"
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        aria-controls="history-drawer"
        aria-label="히스토리 메뉴 열기"
      >
        <Menu className="h-5 w-5" />
      </button>
      {isPortalReady ? createPortal(drawerLayer, document.body) : null}
    </>
  );
}
