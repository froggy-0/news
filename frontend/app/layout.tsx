import type { Metadata } from "next";
import { Instrument_Serif, Inter, JetBrains_Mono } from "next/font/google";

import { ScrollProgressBar } from "@/components/layout/ScrollProgressBar";
import { SiteFooter } from "@/components/layout/SiteFooter";

import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
  weight: ["400", "500", "600", "700", "800", "900"],
});

const jetBrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
  display: "swap",
  weight: ["400", "500", "700"],
});

const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  variable: "--font-instrument-serif",
  display: "swap",
  weight: ["400"],
  style: ["normal", "italic"],
});

export const metadata: Metadata = {
  title: "SOVEREIGN BRIEF",
  description: "글로벌 마켓 데이터의 정교한 연결, 원본의 무결성으로 완성하는 투자 주권.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="ko"
      className={`${inter.variable} ${jetBrainsMono.variable} ${instrumentSerif.variable}`}
    >
      <body>
        <ScrollProgressBar />
        <div className="site-noise" />
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
