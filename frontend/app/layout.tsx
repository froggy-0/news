import type { Metadata } from "next";

import { ScrollProgressBar } from "@/components/layout/ScrollProgressBar";
import { SiteFooter } from "@/components/layout/SiteFooter";

import "./globals.css";

export const metadata: Metadata = {
  title: "SOVEREIGN BRIEF",
  description: "미국 기술주와 비트코인 시장 흐름을 한국어로 빠르게 읽는 정적 브리핑 페이지",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <body>
        <ScrollProgressBar />
        <div className="scanline" />
        <div className="page-shell">
          <div className="page-inner">
            {children}
            <SiteFooter />
          </div>
        </div>
      </body>
    </html>
  );
}
