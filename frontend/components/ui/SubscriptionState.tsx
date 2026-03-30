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
        "rounded-[20px] border px-4 py-3 text-[14px] leading-6 text-white/86",
        tone === "neutral" && "border-white/10 bg-white/[0.03]",
        tone === "success" && "border-[rgba(2,230,0,0.25)] text-[var(--text-primary)]",
        tone === "danger" && "border-[rgba(248,113,113,0.35)] text-[var(--accent-down)]",
      )}
    >
      {children}
    </div>
  );
}
