"use client";

import { ArchiveIcon, HomeIcon, MailIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

export function BottomTabBar() {
  const pathname = usePathname();

  const isHome = pathname === "/";
  const isArchive = pathname.startsWith("/archive");

  return (
    <nav className="bottom-tab-safe fixed inset-x-0 bottom-0 z-[65] border-t border-white/10 bg-black/85 backdrop-blur-md md:hidden">
      <div className="flex">
        <Link
          href="/"
          className={`flex flex-1 flex-col items-center justify-center gap-1 min-h-[56px] ${isHome ? "text-white" : "text-white/40"}`}
        >
          <HomeIcon className="h-5 w-5" />
          <span className="text-[10px] font-mono uppercase tracking-[0.08em]">홈</span>
        </Link>
        <Link
          href="/archive"
          className={`flex flex-1 flex-col items-center justify-center gap-1 min-h-[56px] ${isArchive ? "text-white" : "text-white/40"}`}
        >
          <ArchiveIcon className="h-5 w-5" />
          <span className="text-[10px] font-mono uppercase tracking-[0.08em]">아카이브</span>
        </Link>
        <Link
          href="/#subscribe"
          className="flex flex-1 flex-col items-center justify-center gap-1 min-h-[56px] text-white/40"
        >
          <MailIcon className="h-5 w-5" />
          <span className="text-[10px] font-mono uppercase tracking-[0.08em]">구독</span>
        </Link>
      </div>
    </nav>
  );
}
