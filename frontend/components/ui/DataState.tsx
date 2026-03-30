import React from "react";

import { SectionSkeleton } from "./SectionSkeleton";
import { StateFrame } from "./StateFrame";

export function DataState({
  message,
  title = "Data status",
  tone = "empty",
  family = "utility",
  minHeight,
}: {
  message: string;
  title?: string;
  tone?: "loading" | "partial" | "empty" | "error";
  family?: "reading" | "data" | "utility";
  minHeight?: number;
}) {
  if (tone === "loading") {
    return <SectionSkeleton family={family} minHeight={minHeight ?? 160} lines={family === "reading" ? 3 : 2} />;
  }

  return (
    <StateFrame
      tone={tone}
      family={family}
      title={title}
      description={message}
      minHeight={minHeight}
    />
  );
}
