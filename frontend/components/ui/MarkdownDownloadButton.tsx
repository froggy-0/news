"use client";

export function MarkdownDownloadButton({
  body,
  date,
}: {
  body: string;
  date: string;
}) {
  const handleClick = () => {
    const blob = new Blob([body], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `sovereign-brief-${date}.md`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      className="rounded-full border border-white/15 px-4 py-2 text-xs tracking-[0.18em] text-[var(--text-secondary)] transition hover:border-[var(--accent-gold)] hover:text-[var(--text-primary)]"
    >
      Download MD
    </button>
  );
}
