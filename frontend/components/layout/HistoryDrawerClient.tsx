"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, Menu, X } from "lucide-react";

import type { HistoryMenuEntry } from "@/lib/history";
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
  currentDate,
  initialVisibleCount = 6,
}: {
  entries: HistoryMenuEntry[];
  currentDate?: string;
  initialVisibleCount?: number;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [visibleCount, setVisibleCount] = useState(initialVisibleCount);
  const [isPortalReady, setIsPortalReady] = useState(false);
  const drawerRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const lastActiveElementRef = useRef<HTMLElement | null>(null);
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
      const activeEl = document.activeElement;

      if (event.shiftKey && activeEl === firstElement) {
        event.preventDefault();
        lastElement?.focus();
      } else if (!event.shiftKey && activeEl === lastElement) {
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
            aria-label="브리프 아카이브"
            className="fixed inset-y-0 right-0 z-[100] flex w-full max-w-[380px] flex-col border-l border-white/10 bg-black/95 shadow-[0_0_80px_rgba(0,0,0,0.6)] backdrop-blur-xl"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 28, stiffness: 220 }}
          >
            {/* Header */}
            <div className="flex items-center justify-between gap-4 border-b border-white/8 px-6 py-5">
              <div className="flex items-center gap-3">
                <p className="text-[10px] font-mono uppercase tracking-[0.3em] text-white/40">Archive</p>
                <span className="label-meta rounded-full border border-white/10 px-2.5 py-0.5 text-white/30">
                  {archiveEntries.length}
                </span>
              </div>
              <button
                ref={closeButtonRef}
                type="button"
                onClick={() => setIsOpen(false)}
                className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-white/10 text-white/50 transition hover:border-white/25 hover:text-white"
                aria-label="닫기"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* List */}
            <div className="flex-1 overflow-y-auto px-4 py-4">
              {archiveEntries.length > 0 ? (
                <div className="grid gap-1">
                  {archiveEntries.slice(0, visibleCount).map((entry) => (
                    <Link
                      key={entry.date}
                      href={entry.href}
                      className="group flex items-center justify-between gap-4 rounded-xl px-4 py-3.5 text-white/65 transition-all duration-200 hover:bg-white/[0.05] hover:text-white"
                      onClick={() => setIsOpen(false)}
                    >
                      <div className="min-w-0 space-y-0.5">
                        <p className="text-[0.95rem] font-semibold tracking-tight text-white">
                          {formatPublicationDate(entry.date)}
                        </p>
                        <p className="text-xs text-white/38">
                          {archiveRelativeLabel(entry.date, currentDate)}
                        </p>
                      </div>
                      <ArrowRight className="h-4 w-4 shrink-0 text-white/25 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-white/60" />
                    </Link>
                  ))}
                </div>
              ) : (
                <p className="px-4 py-6 text-sm leading-6 text-white/40">
                  아직 이전 발행본이 없습니다.
                </p>
              )}

              {visibleCount < archiveEntries.length ? (
                <button
                  type="button"
                  onClick={() => setVisibleCount((count) => count + 8)}
                  className="label-meta mt-1 w-full rounded-xl px-4 py-3 text-white/32 transition hover:bg-white/[0.03] hover:text-white/60"
                >
                  더 보기
                </button>
              ) : null}
            </div>

            {/* Footer */}
            <div className="border-t border-white/8 px-4 py-4">
              <Link
                href="/archive"
                className="group flex items-center justify-between rounded-xl border border-white/10 px-4 py-3.5 text-white/60 transition-all duration-200 hover:border-white/20 hover:bg-white/[0.04] hover:text-white"
                onClick={() => setIsOpen(false)}
              >
                <p className="text-sm font-medium tracking-tight">전체 아카이브</p>
                <ArrowRight className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-0.5" />
              </Link>
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
