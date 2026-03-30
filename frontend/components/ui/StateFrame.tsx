import React from "react";
import type { CSSProperties, ReactNode } from "react";
import clsx from "clsx";

export type CardFamily = "reading" | "data" | "utility";
export type StateTone = "loading" | "partial" | "empty" | "error";

export function StateFrame({
  tone,
  family,
  title,
  description,
  minHeight,
  children,
}: {
  tone: StateTone;
  family: CardFamily;
  title: string;
  description?: string;
  minHeight?: number;
  children?: ReactNode;
}) {
  return (
    <div
      className={clsx(
        "state-frame",
        `state-frame-${tone}`,
        `state-frame-${family}`,
      )}
      style={minHeight ? ({ minHeight: `${minHeight}px` } satisfies CSSProperties) : undefined}
      data-tone={tone}
      data-family={family}
    >
      <div className="space-y-2">
        <p className="label-meta">{title}</p>
        {description ? <p className="state-frame-copy">{description}</p> : null}
      </div>
      {children ? <div className="state-frame-extra">{children}</div> : null}
    </div>
  );
}
