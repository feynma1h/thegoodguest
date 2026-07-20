import type { Metadata } from "next";
import { DM_Mono, Geist } from "next/font/google";
import Link from "next/link";

import Wordmark from "@/components/Wordmark";
import { PillLink } from "@/components/ui/spring";
import { apiMode } from "@/lib/api";
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
  const mode = apiMode();
  return (
    <html lang="en" className="dark">
      <body
        className={`${geistSans.variable} ${dmMono.variable} min-h-screen bg-background font-sans text-foreground antialiased`}
      >
        <header className="sticky top-0 z-20 border-b border-white/[0.06] bg-background/70 backdrop-blur-xl">
          <nav className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
            <Link href="/" className="transition-opacity hover:opacity-70">
              <Wordmark />
            </Link>
            <div className="flex items-center gap-6 text-sm">
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
              <PillLink href="/new" className="!px-4 !py-1.5">
                New room
              </PillLink>
              {mode !== "live" && (
                <span
                  className="font-mono text-[10px] text-zinc-600"
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
