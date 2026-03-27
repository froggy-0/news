import type { Metadata } from "next";
import { IBM_Plex_Mono, Newsreader, Noto_Sans_KR, Noto_Serif_KR, Space_Grotesk } from "next/font/google";

import { ScrollProgressBar } from "@/components/layout/ScrollProgressBar";
import { SiteFooter } from "@/components/layout/SiteFooter";

import "./globals.css";

const newsreader = Newsreader({
  subsets: ["latin"],
  weight: ["400", "700"],
  style: ["normal", "italic"],
  variable: "--font-newsreader",
  display: "swap",
  axes: ["opsz"],
});

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  variable: "--font-space-grotesk",
  display: "swap",
});

const ibmPlexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-ibm-plex-mono",
  display: "swap",
});

const notoSansKR = Noto_Sans_KR({
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  variable: "--font-noto-sans-kr",
  display: "swap",
});

const notoSerifKR = Noto_Serif_KR({
  subsets: ["latin"],
  weight: ["400", "600", "700"],
  variable: "--font-noto-serif-kr",
  display: "swap",
});

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
    <html
      lang="ko"
      className={`${newsreader.variable} ${spaceGrotesk.variable} ${ibmPlexMono.variable} ${notoSansKR.variable} ${notoSerifKR.variable}`}
    >
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
