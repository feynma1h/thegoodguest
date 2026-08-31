import type { Metadata } from "next";
import { Instrument_Sans, JetBrains_Mono, Source_Serif_4 } from "next/font/google";

import SiteFooter from "@/components/SiteFooter";
import SiteNav from "@/components/SiteNav";
import { BRAND_NAME } from "@/components/Wordmark";
import "./globals.css";

const instrumentSans = Instrument_Sans({
  variable: "--font-instrument-sans",
  subsets: ["latin"],
});
// The guest's voice and display statements (italic serif); optical
// sizing on so display sizes render with proper drawing.
const sourceSerif = Source_Serif_4({
  variable: "--font-source-serif",
  subsets: ["latin"],
  style: ["normal", "italic"],
  axes: ["opsz"],
});
// Mono is eyebrow labels and machine data — identifiers, coordinates,
// reasoning traces (decision 0057). JetBrains Mono is the brand artwork's
// own mono (decision 0248).
const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: BRAND_NAME,
  description:
    "Scan a room with your phone. Meet it again on your desk — real, in 3D, exactly as you live in it — with a guest who understands it.",
  // Share card. The PNG is re-exported from docs/product/og-card.html
  // whenever the identity moves. og/twitter title + description inherit
  // the fields above.
  metadataBase: new URL("https://thegoodguest.web.app"),
  openGraph: {
    type: "website",
    url: "/",
    images: [
      {
        url: "/og-card.png",
        width: 1200,
        height: 630,
        alt: "Every home contains a version of itself its owner has never seen — beside the measured floor plan of a scanned room.",
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
        className={`${instrumentSans.variable} ${sourceSerif.variable} ${jetbrainsMono.variable} min-h-screen bg-paper font-sans text-ink antialiased`}
      >
        <SiteNav />
        <main>{children}</main>
        <SiteFooter />
      </body>
    </html>
  );
}
