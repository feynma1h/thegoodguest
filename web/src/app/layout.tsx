import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";

import { apiMode } from "@/lib/api";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "RoomStudio",
  description: "Capture a room with your iPhone. Edit it anywhere.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const mode = apiMode();
  return (
    <html lang="en" className="dark">
      <body
        className={`${geistSans.variable} ${geistMono.variable} min-h-screen bg-[#09090c] font-sans text-zinc-100 antialiased`}
      >
        <header className="sticky top-0 z-20 border-b border-zinc-800/80 bg-[#09090c]/80 backdrop-blur">
          <nav className="mx-auto flex h-14 max-w-5xl items-center justify-between px-6">
            <Link href="/" className="text-sm font-semibold tracking-wide">
              room<span className="text-sky-400">studio</span>
            </Link>
            <div className="flex items-center gap-6 text-sm text-zinc-400">
              <Link href="/scenes" className="transition hover:text-zinc-100">
                Scenes
              </Link>
              <Link href="/viewer" className="transition hover:text-zinc-100">
                Viewer
              </Link>
              <Link href="/capture" className="transition hover:text-zinc-100">
                Capture
              </Link>
              {mode !== "live" && (
                <span
                  className="rounded-md bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-300 ring-1 ring-inset ring-amber-500/30"
                  title="Data served from local fixtures / dev auth. Real sign-in is blocked on the iOS account-linking work (decision 0051)."
                >
                  {mode === "mock" ? "mock data" : "local API"}
                </span>
              )}
            </div>
          </nav>
        </header>
        <main className="mx-auto max-w-5xl px-6 py-10">{children}</main>
      </body>
    </html>
  );
}
