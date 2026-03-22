const dateFormatter = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "long",
  day: "numeric",
  weekday: "short",
});

const timeFormatter = new Intl.DateTimeFormat("ko-KR", {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});
const INVALID_HEADLINE_PREFIXES = ["참고 출처", "source:"];

export function formatIssueDate(value: string): string {
  return dateFormatter.format(new Date(value));
}

export function formatIssueTime(value: string): string {
  return timeFormatter.format(new Date(value));
}

export function formatRelativeTime(value: string): string {
  const target = new Date(value).getTime();
  const diffMinutes = Math.round((Date.now() - target) / 60000);

  if (diffMinutes < 60) {
    return `${Math.max(diffMinutes, 0)}분 전`;
  }
  if (diffMinutes < 24 * 60) {
    return `${Math.floor(diffMinutes / 60)}시간 전`;
  }
  return `${Math.floor(diffMinutes / (24 * 60))}일 전`;
}

export function trendTone(trend: "up" | "down" | "neutral" | null): "up" | "down" | "neutral" {
  return trend ?? "neutral";
}

export function qualityLabel(value: "ok" | "degraded" | "critical"): string {
  if (value === "degraded") {
    return "일부 데이터 누락";
  }
  if (value === "critical") {
    return "신뢰도 낮음";
  }
  return "정상 수집";
}

export function displayHeadline(value: string): string {
  return value.replace(/^[\s\-–—•●▪◦①-⑳0-9.]+/, "").trim();
}

export function hasUsableHeadline(value: string | null | undefined): boolean {
  const normalized = displayHeadline(String(value || ""));
  if (!normalized) {
    return false;
  }
  const lowered = normalized.toLowerCase();
  if (INVALID_HEADLINE_PREFIXES.some((prefix) => lowered.startsWith(prefix))) {
    return false;
  }
  if (lowered.includes("http://") || lowered.includes("https://")) {
    return false;
  }
  return /[가-힣]/.test(normalized);
}
