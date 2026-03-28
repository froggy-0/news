import clsx from "clsx";

export function SubscriptionState({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "success" | "danger";
  children: React.ReactNode;
}) {
  return (
    <div
      className={clsx(
        "data-state",
        tone === "success" && "border-[rgba(2,230,0,0.25)] text-[var(--text-primary)]",
        tone === "danger" && "border-[rgba(248,113,113,0.35)] text-[var(--accent-down)]",
      )}
    >
      {children}
    </div>
  );
}
