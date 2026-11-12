import type { Metadata } from "next";
import { Albert_Sans, JetBrains_Mono, Newsreader } from "next/font/google";

import SiteFooter from "@/components/SiteFooter";
import SiteNav from "@/components/SiteNav";
import { BRAND_NAME } from "@/components/Wordmark";
import "./globals.css";

// All interface text (decision 0361).
const albertSans = Albert_Sans({
  variable: "--font-albert-sans",
  subsets: ["latin"],
});
// Display headlines and the guest's voice (italic). Optical sizing on, so a
// 96px headline and an 18px guest line each get their own drawing.
const newsreader = Newsreader({
  variable: "--font-newsreader",
  subsets: ["latin"],
  style: ["normal", "italic"],
  axes: ["opsz"],
});
// Measurements only. JetBrains Mono is the brand artwork's own mono
// (decision 0248).
const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: BRAND_NAME,
  description:
    "Scan a room with your phone. Meet it again on your desk — real, in 3D, exactly as you live in it — with a guest who understands it.",
  // Share card. The PNG is drawn by the site itself and re-exported from
  // app/share-card/page.tsx (its header has the command) whenever the
  // landing's claim or the identity moves. og/twitter title + description
  // inherit the fields above.
  metadataBase: new URL("https://thegoodguest.web.app"),
  openGraph: {
    type: "website",
    url: "/",
    images: [
      {
        url: "/og-card.png",
        width: 1200,
        height: 630,
        alt: "Meet your room again. Walk a room with your iPhone and it stands back up in 3D, at its true size — beside a sample room, cut away so you can see in.",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    images: ["/og-card.png"],
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body
        className={`${albertSans.variable} ${newsreader.variable} ${jetbrainsMono.variable} flex min-h-dvh flex-col bg-paper font-sans text-ink antialiased`}
      >
        <SiteNav />
        {/* flex-1: a short page still puts the footer at the window's foot. */}
        <main className="flex-1">{children}</main>
        <SiteFooter />
      </body>
    </html>
  );
}
