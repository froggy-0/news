import type { Metadata } from "next";
import { DM_Sans, IBM_Plex_Mono, Inter, JetBrains_Mono } from "next/font/google";

import { AtmosphericCanvas } from "@/components/layout/AtmosphericCanvas";
import { ScrollProgressBar } from "@/components/layout/ScrollProgressBar";
import { SiteFooter } from "@/components/layout/SiteFooter";

import "./globals.css";

const dmSans = DM_Sans({
  subsets: ["latin"],
  variable: "--font-dm-sans",
  display: "swap",
  weight: ["400", "500", "600", "700", "800", "900"],
});

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
  weight: ["400", "500", "600", "700"],
});

const jetBrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
  display: "swap",
  weight: ["400", "500", "700"],
});

const ibmPlexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  variable: "--font-ibm-plex-mono",
  display: "swap",
  weight: ["400", "500", "600", "700"],
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
      className={`${dmSans.variable} ${inter.variable} ${jetBrainsMono.variable} ${ibmPlexMono.variable}`}
    >
      <body>
        <AtmosphericCanvas />
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
