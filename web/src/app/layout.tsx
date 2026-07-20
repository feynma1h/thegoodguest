import type { Metadata } from "next";
import { DM_Mono, Geist } from "next/font/google";

import SiteNav from "@/components/SiteNav";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
// Mono is reserved for machine data — identifiers, coordinates, reasoning
// traces (decision 0056). It never appears decoratively.
const dmMono = DM_Mono({
  variable: "--font-dm-mono",
  subsets: ["latin"],
  weight: ["300", "400", "500"],
});

export const metadata: Metadata = {
  // Working title — no product name chosen yet (see Wordmark.tsx).
  title: "roomstudio",
  description:
    "Your room has a version of itself you've never seen. Scan it, understand it, improve it.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="dark">
      <body
        className={`${geistSans.variable} ${dmMono.variable} min-h-screen bg-background font-sans text-foreground antialiased`}
      >
        <SiteNav />
        <main>{children}</main>
      </body>
    </html>
  );
}
