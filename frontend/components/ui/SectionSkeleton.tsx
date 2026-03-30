import React from "react";
import clsx from "clsx";

import type { CardFamily } from "./StateFrame";

export function SectionSkeleton({
  family,
  lines = 3,
  minHeight,
}: {
  family: CardFamily;
  lines?: number;
  minHeight: number;
}) {
  return (
    <div
      className={clsx("section-skeleton", `section-skeleton-${family}`)}
      style={{ minHeight: `${minHeight}px` }}
      aria-hidden="true"
    >
      <div className="space-y-3">
        {Array.from({ length: lines }).map((_, index) => (
          <span
            key={`${family}-${index}`}
            className="section-skeleton-line"
            style={{ width: index === lines - 1 ? "68%" : index === 0 ? "34%" : "100%" }}
          />
        ))}
      </div>
    </div>
  );
}
