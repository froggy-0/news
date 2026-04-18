"use client";

import React, { useEffect, useState } from "react";

import { formatRelativeTime } from "@/lib/format";

export function RelativeTime({ value }: { value: string }) {
  const [label, setLabel] = useState<string>("");

  useEffect(() => {
    setLabel(formatRelativeTime(value));
  }, [value]);

  return <span>{label}</span>;
}
