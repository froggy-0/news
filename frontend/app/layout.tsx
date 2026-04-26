import type { Metadata } from "next";
import { Instrument_Serif, Inter, JetBrains_Mono } from "next/font/google";

import { AtmosphericCanvas } from "@/components/layout/AtmosphericCanvas";
import { BottomTabBar } from "@/components/layout/BottomTabBar";
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
  description:
    "Structured market intelligence — quantitative signals, news sentiment, and daily briefings for sovereign investors.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${jetBrainsMono.variable} ${instrumentSerif.variable}`}
    >
      <body>
        <AtmosphericCanvas />
        <ScrollProgressBar />
        <div className="site-noise" />
        <div className="page-shell">
          <div className="page-inner pb-14 md:pb-0">
            {children}
            <SiteFooter />
          </div>
          <BottomTabBar />
        </div>
      </body>
    </html>
  );
}
