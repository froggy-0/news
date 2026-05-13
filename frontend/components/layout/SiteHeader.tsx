import Link from "next/link";

export function SiteHeader({
  variant = "home",
}: {
  variant?: "home" | "archive-list" | "archive-detail";
}) {
  return (
    <header className="fixed inset-x-0 top-0 z-[70] border-b border-[#2b3139] bg-[#161a1e]/95 backdrop-blur-md">
      <div className="mx-auto flex h-14 w-full items-center justify-between gap-4 px-4 md:px-6">
        {/* Logo */}
        <div className="flex items-center gap-3">
          <Link href="/" className="flex items-center gap-2.5 group">
            <span className="flex h-6 w-6 items-center justify-center rounded-sm bg-[#f0b90b]">
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden>
                <rect x="6" y="0" width="2" height="2" fill="#1e2329"/>
                <rect x="3" y="3" width="2" height="2" fill="#1e2329"/>
                <rect x="9" y="3" width="2" height="2" fill="#1e2329"/>
                <rect x="0" y="6" width="2" height="2" fill="#1e2329"/>
                <rect x="6" y="6" width="2" height="2" fill="#1e2329"/>
                <rect x="12" y="6" width="2" height="2" fill="#1e2329"/>
                <rect x="3" y="9" width="2" height="2" fill="#1e2329"/>
                <rect x="9" y="9" width="2" height="2" fill="#1e2329"/>
                <rect x="6" y="12" width="2" height="2" fill="#1e2329"/>
              </svg>
            </span>
            <span
              className="font-bold tracking-tight text-[#eaecef] transition-colors group-hover:text-white"
              style={{ fontFamily: "var(--font-ibm-plex-mono, var(--font-jetbrains-mono))", fontSize: "15px", letterSpacing: "-0.02em" }}
            >
              SOVEREIGN<span className="text-[#f0b90b]">.</span>
            </span>
          </Link>
          <span className="hidden h-4 w-px bg-[#2b3139] md:block" />
          <span
            className="hidden text-[10px] font-medium uppercase tracking-[0.14em] text-[#474d57] md:inline"
            style={{ fontFamily: "var(--font-ibm-plex-mono, var(--font-jetbrains-mono))" }}
          >
            {variant === "home" ? "Intelligence" : variant === "archive-list" ? "Archive" : "Brief"}
          </span>
        </div>

        {/* Live dot + nav */}
        <nav className="hidden items-center gap-1 md:flex">
          {(
            [
              { href: "/archive", label: "Archive" },
              { href: "/analysis", label: "Analysis" },
            ] as const
          ).map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              className="rounded px-3 py-1.5 text-[13px] font-medium text-[#848e9c] transition-colors hover:bg-[#2b3139] hover:text-[#eaecef]"
              style={{ fontFamily: "var(--font-dm-sans)" }}
            >
              {label}
            </Link>
          ))}
          <span className="mx-2 h-4 w-px bg-[#2b3139]" />
          <a
            href="/#subscribe"
            className="flex h-8 items-center gap-1.5 rounded px-4 text-[13px] font-bold text-[#0a0c0e] transition-all hover:-translate-y-px hover:opacity-95"
            style={{
              fontFamily: "var(--font-dm-sans)",
              background: "linear-gradient(135deg, #f5c430 0%, #e8a800 100%)",
              boxShadow: "0 2px 12px rgba(240,185,11,0.22), inset 0 1px 0 rgba(255,255,255,0.14)",
            }}
          >
            Subscribe
          </a>
        </nav>

        {/* mobile */}
        <div className="flex items-center gap-2 md:hidden">
          <a
            href="/#subscribe"
            className="flex h-8 items-center rounded px-3 text-[12px] font-bold text-[#0a0c0e]"
            style={{
              background: "linear-gradient(135deg, #f5c430 0%, #e8a800 100%)",
              boxShadow: "0 2px 10px rgba(240,185,11,0.20)",
            }}
          >
            Subscribe
          </a>
        </div>
      </div>
    </header>
  );
}
