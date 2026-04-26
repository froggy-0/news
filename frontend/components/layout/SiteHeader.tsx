import Link from "next/link";
import { ArrowRight } from "lucide-react";

export function SiteHeader({
  variant = "home",
}: {
  variant?: "home" | "archive-list" | "archive-detail";
}) {
  const variantCopy =
    variant === "home" ? "Live Intelligence" : variant === "archive-list" ? "Archive" : "Brief";

  return (
    <header className="fixed inset-x-0 top-0 z-[70] border-b border-[rgba(169,146,125,0.12)] bg-[#0a0908]/80 backdrop-blur-md">
      <div className="mx-auto flex h-[68px] w-full items-center justify-between gap-4 px-6 md:px-20">
        <div className="flex min-w-0 items-center gap-3">
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--accent-primary)]" />
          <Link
            href="/"
            className="truncate text-lg font-semibold tracking-normal text-[var(--smoke)] transition-colors hover:text-[var(--taupe)] md:text-[22px]"
          >
            SOVEREIGN BRIEF
          </Link>
          <span className="hidden text-[11px] font-medium uppercase tracking-[0.14em] text-[var(--taupe)]/60 md:inline">
            {variantCopy}
          </span>
        </div>

        <nav className="hidden items-center gap-8 md:flex">
          <Link className="text-sm tracking-normal text-[var(--taupe)] transition-colors hover:text-[var(--smoke)]" href="/archive">
            Archive
          </Link>
          <Link className="text-sm tracking-normal text-[var(--taupe)] transition-colors hover:text-[var(--smoke)]" href="/analysis">
            Analysis
          </Link>
          <Link className="text-sm tracking-normal text-[var(--taupe)] transition-colors hover:text-[var(--smoke)]" href="/privacy">
            Privacy
          </Link>
          <a
            href="/#subscribe"
            className="inline-flex items-center gap-2 rounded-md border border-[var(--accent-primary)] px-4 py-2 text-[13px] font-medium text-[var(--smoke)] transition-colors hover:bg-[var(--accent-primary)]/20"
          >
            Subscribe
            <ArrowRight className="h-3.5 w-3.5" />
          </a>
        </nav>

        <div className="flex items-center md:hidden">
          <a
            href="/#subscribe"
            className="inline-flex items-center rounded-md border border-[var(--accent-primary)] px-4 py-2 text-xs font-medium uppercase tracking-[0.06em] text-[var(--smoke)] transition-colors hover:bg-[var(--accent-primary)]/20"
          >
            Subscribe
          </a>
        </div>
      </div>
    </header>
  );
}
