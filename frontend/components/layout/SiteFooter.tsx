import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="relative z-10 border-t border-[rgba(169,146,125,0.10)] bg-[#0a0908]/88 px-6 py-6 backdrop-blur-md md:px-20 md:py-8">
      <div className="mx-auto flex w-full flex-col items-center justify-between gap-3 text-center md:flex-row md:text-left">
        <div className="flex items-center gap-2">
          <span
            className="h-1.5 w-1.5 rounded-full bg-[#00ffff]"
            style={{ boxShadow: "0 0 4px rgba(0,255,255,0.55)" }}
          />
          <div className="text-sm font-semibold tracking-normal text-[var(--taupe)]/60">SOVEREIGN BRIEF</div>
        </div>
        <nav className="flex flex-wrap justify-center gap-x-5 gap-y-2">
          <Link className="footer-link" href="/archive">
            Archive
          </Link>
          <Link className="footer-link" href="/analysis">
            Analysis
          </Link>
          <Link className="footer-link" href="/privacy">
            Privacy Policy
          </Link>
          <a className="footer-link" href="/rss.xml">
            RSS Feed
          </a>
          <a className="footer-link" href="/llms.txt">
            LLM Index
          </a>
        </nav>
        <div className="text-[10px] text-[var(--taupe)]/35 md:text-xs">
          Market intelligence · 정보 제공 목적
        </div>
      </div>
    </footer>
  );
}
