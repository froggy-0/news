"use client";

import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

export function RevealSection({
  id,
  className,
  children,
  threshold = 0.34,
  delayMs = 180,
}: {
  id?: string;
  className?: string;
  children: ReactNode;
  threshold?: number;
  delayMs?: number;
}) {
  const sectionRef = useRef<HTMLElement | null>(null);
  const [revealed, setRevealed] = useState(false);

  useEffect(() => {
    const node = sectionRef.current;
    if (!node || revealed) {
      return;
    }

    let activationTimer: ReturnType<typeof setTimeout> | null = null;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          activationTimer = setTimeout(() => {
            setRevealed(true);
          }, delayMs);
          observer.disconnect();
        }
      },
      { threshold },
    );

    observer.observe(node);
    return () => {
      observer.disconnect();
      if (activationTimer) {
        clearTimeout(activationTimer);
      }
    };
  }, [delayMs, revealed, threshold]);

  return (
    <section
      id={id}
      ref={sectionRef}
      className={className ? `reveal-on-view ${className}` : "reveal-on-view"}
      data-revealed={revealed ? "true" : "false"}
    >
      {children}
    </section>
  );
}
