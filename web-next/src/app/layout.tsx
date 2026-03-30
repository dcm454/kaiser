import type { Metadata } from "next";
import { JetBrains_Mono, Plus_Jakarta_Sans, Sora } from "next/font/google";
import "./globals.css";

const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "https://kaiser-caaa4.web.app";

const displayFont = Sora({
  subsets: ["latin"],
  variable: "--font-display",
  weight: ["400", "500", "600", "700"],
});

const bodyFont = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-body",
  weight: ["400", "500", "600", "700"],
});

const monoFont = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: "Play Kaiser Online Free | No Ads",
    template: "%s | Play Kaiser Online",
  },
  description:
    "Play Kaiser online free with friends or AI. No ads, no downloads. Learn bidding, scoring, no-trump strategy, and trick-taking rules in this multiplayer card game.",
  applicationName: "Play Kaiser Online",
  keywords: [
    "play kaiser online",
    "play kaiser free",
    "no ads card game",
    "kaiser card game",
    "multiplayer trick taking game",
    "partnership card game",
    "kaiser no trump",
  ],
  alternates: {
    canonical: "/",
  },
  openGraph: {
    title: "Play Kaiser Online Free | No Ads",
    description:
      "Play Kaiser online free with friends or AI. No ads, no downloads, quick multiplayer setup, and full rules guidance.",
    url: siteUrl,
    siteName: "Play Kaiser Online",
    type: "website",
    locale: "en_US",
    images: [
      {
        url: "/icon.svg",
        width: 512,
        height: 512,
        alt: "Play Kaiser Online Free - No Ads",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Play Kaiser Online Free | No Ads",
    description:
      "Play Kaiser online free with friends or AI. No ads, no downloads, and fast multiplayer rounds.",
    images: ["/icon.svg"],
  },
  icons: {
    icon: "/icon.svg",
  },
  category: "games",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${displayFont.variable} ${bodyFont.variable} ${monoFont.variable}`}>{children}</body>
    </html>
  );
}
