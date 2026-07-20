import AmbientHero from "@/components/AmbientHero";
import { PillLink } from "@/components/ui/spring";

export default function Home() {
  return (
    <>
      <AmbientHero>
        <div className="mx-auto flex min-h-[82vh] max-w-4xl flex-col items-center justify-center px-6 text-center">
          <h1 className="max-w-3xl text-balance text-5xl font-semibold leading-[1.05] tracking-[-0.03em] sm:text-6xl">
            Your room has a version of itself
            <span className="text-zinc-500"> you&rsquo;ve never seen.</span>
          </h1>
          <p className="mt-8 max-w-xl text-pretty text-lg leading-relaxed text-zinc-400">
            Scan it once with your iPhone. It comes back as a living 3D space —
            understood object by object, light by light — so deciding what to
            change stops being guesswork.
          </p>
          <div className="mt-12 flex items-center gap-4">
            <PillLink href="/rooms" className="!px-7 !py-3">
              Show me
            </PillLink>
            <PillLink href="/new" variant="ghost" className="!px-7 !py-3">
              Scan a room
            </PillLink>
          </div>
        </div>
      </AmbientHero>

      <section className="mx-auto max-w-3xl px-6 py-28 text-center">
        <div className="space-y-6 text-2xl font-light leading-snug tracking-tight text-zinc-400 sm:text-[1.6rem]">
          <p>Most rooms are shaped by what was available, not by what was wanted.</p>
          <p>Most design tools show you other people&rsquo;s rooms.</p>
          <p className="font-normal text-foreground">This one shows you yours.</p>
        </div>
      </section>

      <section className="border-t border-white/[0.06]">
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
              <p className="text-xs font-medium text-zinc-600">{step.n}</p>
              <h2 className="mt-3 text-lg font-semibold tracking-tight text-foreground">
                {step.title}
              </h2>
              <p className="mt-3 text-sm leading-relaxed text-zinc-500">{step.body}</p>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
