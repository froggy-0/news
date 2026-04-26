import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="mt-24 border-t border-[rgba(255,220,140,0.08)] bg-[#0b0906]/90 px-8 py-14 backdrop-blur-md">
      <div className="mx-auto flex w-full max-w-6xl flex-col items-center gap-6 text-center">
        <div className="text-lg font-bold tracking-[-0.08em] text-white">SOVEREIGN BRIEF</div>
        <nav className="flex flex-wrap justify-center gap-x-6 gap-y-3">
          <Link className="footer-link" href="/archive">
            Archive
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
        <p className="max-w-2xl text-sm leading-relaxed text-white/40">
          Precision-engineered market intelligence — sovereign clarity before the narrative forms.
        </p>
        <div className="text-[10px] uppercase tracking-[0.24em] text-white/28">
          © 2026 SOVEREIGN BRIEF · PUBLIC STATIC EDITION
        </div>
      </div>
    </footer>
  );
}
