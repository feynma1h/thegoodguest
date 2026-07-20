import type { Metadata } from "next";
import { DM_Mono, Fraunces, Geist } from "next/font/google";
import Link from "next/link";

import Wordmark from "@/components/Wordmark";
import { apiMode } from "@/lib/api";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
// Serif = feeling, mono = thinking (founding draft's type system, decision 0055).
const fraunces = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
  axes: ["opsz", "SOFT", "WONK"],
});
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
  const mode = apiMode();
  return (
    <html lang="en" className="dark">
      <body
        className={`${geistSans.variable} ${fraunces.variable} ${dmMono.variable} min-h-screen bg-background font-sans text-foreground antialiased`}
      >
        <header className="sticky top-0 z-20 border-b border-white/5 bg-background/70 backdrop-blur-md">
          <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
            <Link href="/" className="transition-opacity hover:opacity-80">
              <Wordmark />
            </Link>
            <div className="flex items-center gap-7 text-sm">
              <Link
                href="/rooms"
                className="text-zinc-400 transition-colors hover:text-foreground"
              >
                Rooms
              </Link>
              {mode !== "live" && (
                <Link
                  href="/viewer"
                  className="text-zinc-600 transition-colors hover:text-zinc-400"
                  title="Developer viewer — drag-drop splat files, load fixtures"
                >
                  Viewer
                </Link>
              )}
              <Link
                href="/new"
                className="ease-soft rounded-full bg-accent px-4 py-1.5 text-sm font-medium text-[#171207] transition-all duration-200 hover:scale-[1.03] hover:bg-[#ecb26e] active:scale-[0.98]"
              >
                New room
              </Link>
              {mode !== "live" && (
                <span
                  className="font-mono text-[10px] uppercase tracking-widest text-zinc-600"
                  title="Data served from local fixtures / dev auth. Real sign-in is blocked on the iOS account-linking work (decision 0051)."
                >
                  {mode === "mock" ? "mock" : "local"}
                </span>
              )}
            </div>
          </nav>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
