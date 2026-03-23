import type { Metadata } from "next";

import { ScrollProgressBar } from "@/components/layout/ScrollProgressBar";
import { SiteFooter } from "@/components/layout/SiteFooter";

import "./globals.css";

export const metadata: Metadata = {
  title: "SOVEREIGN BRIEF",
  description: "흩어진 영문 기사와 공식 시그널을 한국어 판단으로 압축해 읽는 공개 브리프",
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
