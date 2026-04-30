"use client";

import React, { useEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

export function RevealSection({
  id,
  className,
  children,
  revealAt = 0.82,
  visibleRatio = 0.01,
  delayMs = 80,
  distancePx = 10,
  durationMs = 260,
}: {
  id?: string;
  className?: string;
  children?: ReactNode;
  revealAt?: number;
  visibleRatio?: number;
  delayMs?: number;
  distancePx?: number;
  durationMs?: number;
}) {
  const sectionRef = useRef<HTMLElement | null>(null);
  const [revealed, setRevealed] = useState(false);
  const normalizedRevealAt = clamp(revealAt, 0.5, 0.95);
  const normalizedVisibleRatio = clamp(visibleRatio, 0, 0.5);

  useEffect(() => {
    const node = sectionRef.current;
    if (!node || revealed) {
      return;
    }

    let activationTimer: ReturnType<typeof setTimeout> | null = null;
    let animationFrame: number | null = null;

    const reveal = () => {
      if (activationTimer) {
        clearTimeout(activationTimer);
      }
      setRevealed(true);
    };

    const scheduleReveal = () => {
      if (activationTimer) {
        return;
      }
      activationTimer = setTimeout(reveal, delayMs);
    };

    const revealFromViewport = () => {
      const rect = node.getBoundingClientRect();
      const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
      const triggerLine = viewportHeight * normalizedRevealAt;
      return rect.top <= triggerLine && rect.bottom >= 0;
    };

    const checkViewport = () => {
      if (revealFromViewport()) {
        scheduleReveal();
      }
    };

    const requestViewportCheck = () => {
      if (animationFrame !== null) {
        return;
      }
      animationFrame = window.requestAnimationFrame(() => {
        animationFrame = null;
        checkViewport();
      });
    };

    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      reveal();
      return;
    }

    if (typeof window.IntersectionObserver !== "function") {
      checkViewport();
      window.addEventListener("scroll", requestViewportCheck, { passive: true });
      window.addEventListener("resize", requestViewportCheck);
      return () => {
        window.removeEventListener("scroll", requestViewportCheck);
        window.removeEventListener("resize", requestViewportCheck);
        if (activationTimer) {
          clearTimeout(activationTimer);
        }
        if (animationFrame !== null) {
          window.cancelAnimationFrame(animationFrame);
        }
      };
    }

    if (revealFromViewport()) {
      scheduleReveal();
      return () => {
        if (activationTimer) {
          clearTimeout(activationTimer);
        }
      };
    }

    const bottomMarginPercent = Math.round((1 - normalizedRevealAt) * 100);
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          scheduleReveal();
          observer.disconnect();
        }
      },
      {
        rootMargin: `0px 0px -${bottomMarginPercent}% 0px`,
        threshold: normalizedVisibleRatio,
      },
    );

    observer.observe(node);
    window.addEventListener("scroll", requestViewportCheck, { passive: true });
    window.addEventListener("resize", requestViewportCheck);
    return () => {
      observer.disconnect();
      window.removeEventListener("scroll", requestViewportCheck);
      window.removeEventListener("resize", requestViewportCheck);
      if (activationTimer) {
        clearTimeout(activationTimer);
      }
      if (animationFrame !== null) {
        window.cancelAnimationFrame(animationFrame);
      }
    };
  }, [delayMs, normalizedRevealAt, normalizedVisibleRatio, revealed]);

  const revealStyle = {
    "--reveal-distance": `${distancePx}px`,
    "--reveal-duration": `${durationMs}ms`,
  } as CSSProperties;

  return (
    <section
      id={id}
      ref={sectionRef}
      className={className ? `reveal-on-view ${className}` : "reveal-on-view"}
      data-revealed={revealed ? "true" : "false"}
      data-reveal-at={normalizedRevealAt}
      data-delay-ms={delayMs}
      style={revealStyle}
    >
      {children}
    </section>
  );
}
