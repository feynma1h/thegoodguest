import Link from "next/link";

import AmbientHero from "@/components/AmbientHero";

export default function Home() {
  return (
    <>
      <AmbientHero>
        <div className="mx-auto flex min-h-[82vh] max-w-4xl flex-col items-center justify-center px-6 text-center">
          <p className="font-mono text-[11px] uppercase tracking-[0.35em] text-zinc-500">
            Spatial intelligence for your home
          </p>
          <h1 className="mt-8 max-w-3xl text-balance font-serif text-5xl font-light leading-[1.08] tracking-tight sm:text-6xl">
            Your room has a version of itself
            <span className="text-accent"> you&rsquo;ve never seen.</span>
          </h1>
          <p className="mt-8 max-w-xl text-pretty text-lg leading-relaxed text-zinc-400">
            Scan it once with your iPhone. It comes back as a living 3D space —
            understood object by object, light by light — so deciding what to
            change stops being guesswork.
          </p>
          <div className="mt-12 flex items-center gap-4">
            <Link
              href="/rooms"
              className="ease-soft rounded-full bg-accent px-7 py-3 text-sm font-medium text-[#171207] transition-all duration-200 hover:scale-[1.03] hover:bg-[#ecb26e] active:scale-[0.98]"
            >
              Show me
            </Link>
            <Link
              href="/new"
              className="ease-soft rounded-full border border-white/10 px-7 py-3 text-sm text-zinc-300 transition-all duration-200 hover:scale-[1.02] hover:border-white/25 hover:text-foreground"
            >
              Scan a room
            </Link>
          </div>
        </div>
      </AmbientHero>

      <section className="mx-auto max-w-3xl px-6 py-28 text-center">
        <div className="space-y-6 font-serif text-2xl font-light leading-snug text-zinc-300 sm:text-[1.7rem]">
          <p>Most rooms are shaped by what was available, not by what was wanted.</p>
          <p>Most design tools show you other people&rsquo;s rooms.</p>
          <p className="text-foreground">This one shows you yours.</p>
        </div>
      </section>

      <section className="border-t border-white/5">
        <div className="mx-auto grid max-w-5xl gap-12 px-6 py-20 sm:grid-cols-3">
          {[
            {
              n: "01",
              title: "Scan",
              body: "A slow walk through the room with your iPhone. Camera, motion, LiDAR — everything is measured, nothing is guessed.",
            },
            {
              n: "02",
              title: "Understand",
              body: "Every object is found, rebuilt in 3D, and placed exactly where it stands — the room as a structure, not a photo.",
            },
            {
              n: "03",
              title: "Decide",
              body: "Explore your space, see how it actually works, and try the versions of it you've been imagining.",
            },
          ].map((step) => (
            <div key={step.n}>
              <p className="font-mono text-xs tracking-widest text-accent-soft">{step.n}</p>
              <h2 className="mt-3 font-serif text-xl text-foreground">{step.title}</h2>
              <p className="mt-3 text-sm leading-relaxed text-zinc-500">{step.body}</p>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
