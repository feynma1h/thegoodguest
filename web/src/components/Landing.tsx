"use client";

/**
 * The landing for a first-time visitor (decision 0361): a daylight page that
 * turns to dusk, carried by one sample room seen four ways — turnable in the
 * hero, standing itself up in "how it works", changed by the guest, and lit
 * by its own lamps at the close. The evening is shown, never announced.
 *
 * Every claim here is one the product makes good on: the guest moves, takes
 * out or turns a piece and shows it at once (api-public guest_tools), and it
 * never computes a distance, so no line here says it does. The room is a
 * hand-built sample and says so; "nothing is generated" speaks of yours.
 */

import { AnimatePresence, motion } from "motion/react";
import { useCallback, useRef, useState } from "react";

import SampleRoom, { type SampleRoomHandle } from "@/components/SampleRoom";
import { VIEW_COUNT } from "@/components/sampleRoomScene";
import { Mark } from "@/components/Wordmark";
import { PillLink } from "@/components/ui/spring";

const EASE = [0.22, 1, 0.36, 1] as const;

function enter(order: number) {
  return {
    initial: { opacity: 0, y: 18 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.7, ease: EASE, delay: 0.08 + order * 0.1 },
  };
}

function Arrow() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M5 12h14" />
      <path d="M13 6l6 6-6 6" />
    </svg>
  );
}

const H2 = "font-serif text-[clamp(2.5rem,4.6vw,4.1rem)] font-light leading-[1.03] tracking-[-0.03em]";

/** ‹ ● ○ ○ ○ › — the four settled views, like the product's room page. */
function ViewControl({ view, onPick }: { view: number; onPick: (v: number) => void }) {
  const step = (d: number) => onPick(view < 0 ? (d > 0 ? 0 : VIEW_COUNT - 1) : (view + d + VIEW_COUNT) % VIEW_COUNT);
  const btn = "grid h-[34px] w-[34px] cursor-pointer place-items-center rounded-full text-ink transition-colors hover:bg-[#eef1f4]";
  return (
    <div role="group" aria-label="Views of the room" className="inline-flex items-center gap-0.5 rounded-full bg-white/90 p-1 shadow-float">
      <button type="button" aria-label="Previous view" className={btn} onClick={() => step(-1)}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M15 6l-6 6 6 6" />
        </svg>
      </button>
      {Array.from({ length: VIEW_COUNT }, (_, i) => (
        <button key={i} type="button" aria-label={`View ${i + 1}`} aria-pressed={view === i} className={btn} onClick={() => onPick(i)}>
          <span className={`block h-[9px] w-[9px] rounded-full border-[1.5px] border-ink transition-colors ${view === i ? "bg-ink" : ""}`} />
        </button>
      ))}
      <button type="button" aria-label="Next view" className={btn} onClick={() => step(1)}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M9 6l6 6-6 6" />
        </svg>
      </button>
    </div>
  );
}

function Hero() {
  const room = useRef<SampleRoomHandle>(null);
  const [view, setView] = useState(-1);
  const pick = useCallback((v: number) => {
    setView(v);
    room.current?.goTo(v);
  }, []);
  return (
    <section className="px-3 pt-2 sm:px-6">
      <div className="relative mx-auto flex max-w-[1392px] flex-col-reverse md:block">
        <div className="relative h-[460px] overflow-hidden rounded-[32px] bg-parchment md:h-[clamp(660px,calc(100vh-100px),860px)]">
          <SampleRoom
            ref={room}
            label="A sample room in 3D, cut away so you can see in: a green sofa, a terracotta armchair, a low bookcase, a sideboard and a plant, lit by daylight through the window"
            free
            view={0}
            shift={0.15}
            fit={0.84}
            onView={setView}
            className="absolute inset-0"
          />
          <p className="pointer-events-none absolute bottom-[34px] left-10 hidden items-center gap-2 text-sm text-ink-2 md:flex">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M12 3v18M3 12h18M12 3l-3 3M12 3l3 3M12 21l-3-3M12 21l3-3M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3" />
            </svg>
            A sample room. Drag to turn it, or pick a view.
          </p>
          <div className="absolute bottom-[26px] left-1/2 -translate-x-1/2 md:left-[67%]">
            <ViewControl view={view} onPick={pick} />
          </div>
        </div>
        <div className="px-3 pb-10 pt-8 md:pointer-events-none md:absolute md:left-16 md:top-[72px] md:max-w-[470px] md:p-0">
          <motion.h1 {...enter(0)} className="font-serif text-[clamp(3.5rem,6.6vw,6.1rem)] font-light leading-[0.94] tracking-[-0.035em] text-ink">
            Meet your room again.
          </motion.h1>
          <motion.p {...enter(1)} className="mt-7 max-w-[26rem] text-[19px] leading-[1.5] text-ink-2 md:text-xl">
            Walk it once with your iPhone. It stands back up here in 3D, at its true size, with a guest who can talk it through.
          </motion.p>
          <motion.div {...enter(2)} className="pointer-events-auto mt-8 flex flex-wrap items-center gap-6">
            <PillLink href="/new" className="!inline-flex items-center gap-2.5 !px-[26px] !py-4 !text-base">
              Scan your first room
              <Arrow />
            </PillLink>
            <a href="#how" className="text-base font-semibold text-ink underline decoration-1 underline-offset-[6px]">
              How it works
            </a>
          </motion.div>
        </div>
      </div>
    </section>
  );
}

const WAITING_LINES = [
  "Your scan made the trip. I’m at the door.",
  "I’m inside — meeting each piece, working out where it stands.",
  "It’s ready. Come in when you have a minute.",
];

function Manifesto() {
  return (
    <section id="why" className="mx-auto max-w-[1280px] px-6 py-24 sm:px-10 md:pb-40 md:pt-44">
      <div className="grid gap-12 md:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)] md:gap-24">
        <h2 className={`${H2} text-ink`}>
          Every home contains a version of itself its owner has never seen.{" "}
          <span className="text-ink-3">The Good Guest helps you find it.</span>
        </h2>
        <div className="md:pt-3">
          <p className="text-lg leading-relaxed text-ink-2">
            It measures your room, rebuilds it, and stays to talk about it. It speaks only from what it measured, and when it can’t see something, it says so.
          </p>
          <ol className="mt-10 flex flex-col gap-6 border-l border-ink/15 pl-[22px]">
            {WAITING_LINES.map((line) => (
              <li key={line} className="font-serif text-[23px] italic leading-[1.35] text-ink">
                {line}
              </li>
            ))}
          </ol>
          <p className="mt-7 text-[15px] leading-normal text-ink-2">What the guest says while your room is rebuilt.</p>
        </div>
      </div>
    </section>
  );
}

const STEPS = [
  { title: "Walk the room", body: "Open the app and walk slowly, corners included. A minute or two is enough." },
  { title: "Watch it stand back up", body: "The measured outline draws itself, the walls rise, and each piece settles where it really stands." },
  { title: "Talk it through", body: "The guest knows every wall and every piece. Ask about the room, and it answers from what it measured." },
] as const;

function HowItWorks() {
  const room = useRef<SampleRoomHandle>(null);
  const [step, setStep] = useState(1);
  const pick = (i: number) => {
    setStep(i);
    if (i === 0) room.current?.setStage("outline");
    else if (i === 1) room.current?.replay("furnished");
    else room.current?.setStage("furnished");
  };
  return (
    <section id="how" className="bg-surface">
      <div className="mx-auto grid max-w-[1280px] items-center gap-12 px-6 py-24 sm:px-10 md:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] md:gap-[72px] md:py-36">
        <div>
          <h2 className={`${H2} mb-10 text-ink`}>From one walk to a room you can turn in your hands.</h2>
          <div role="group" aria-label="How it works" className="border-b border-ink/10">
            {STEPS.map((s, i) => (
              <button
                key={s.title}
                type="button"
                aria-pressed={step === i}
                onClick={() => pick(i)}
                className="group block w-full cursor-pointer border-t border-ink/10 pb-7 pt-6 text-left"
              >
                <span className={`block font-serif text-[34px] font-light leading-[1.1] tracking-[-0.02em] transition-colors group-hover:text-ink ${step === i ? "text-ink" : "text-ink-3"}`}>
                  {s.title}
                </span>
                <span className="mt-2.5 block max-w-[30rem] text-[17px] leading-[1.55] text-ink-2">{s.body}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="relative h-[460px] overflow-hidden rounded-[28px] bg-parchment md:h-[620px]">
          <SampleRoom
            ref={room}
            label="The sample room standing back up: its outline, then the walls, then each piece"
            reveal
            view={0}
            fit={1.05}
            className="absolute inset-0"
          />
          <AnimatePresence>
            {step === 2 && (
              <motion.div
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 8 }}
                transition={{ duration: 0.45, ease: EASE }}
                className="absolute inset-x-6 bottom-6 flex items-start gap-3.5 rounded-[18px] bg-surface px-5 py-[18px] shadow-float"
              >
                <Mark height="13px" className="mt-[7px]" />
                <p className="font-serif text-[19px] italic leading-[1.45] text-ink">
                  The room stood up first — floor, then walls — and your furniture settled in where it belongs. Come look at how it sits.
                </p>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </section>
  );
}

function GuestSection() {
  const room = useRef<SampleRoomHandle>(null);
  const [chairOut, setChairOut] = useState(true);
  const toggle = () => {
    const next = !chairOut;
    setChairOut(next);
    room.current?.setRemoved(next ? ["armchair"] : []);
  };
  const you = "self-end max-w-[82%] rounded-[18px_18px_6px_18px] bg-[#eef1f4] px-4 py-3 text-base leading-[1.45] text-ink";
  const guest = "font-serif text-xl italic leading-[1.45] text-ink";
  return (
    <section id="guest" className="mx-auto max-w-[1280px] px-6 py-24 sm:px-10 md:pb-44 md:pt-36">
      <div className="mb-14 grid items-end gap-8 md:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] md:gap-24">
        <h2 className={`${H2} text-ink`}>Ask about the room. Watch it change.</h2>
        <p className="text-lg leading-relaxed text-ink-2">
          The guest can move a piece, take one out or turn it round, and show you straight away. It never invents a measurement.
        </p>
      </div>
      <div className="grid items-stretch gap-7 md:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
        <div className="flex min-h-[620px] flex-col gap-[22px] rounded-[28px] bg-surface p-[30px] shadow-lift">
          <div className="flex items-center gap-2.5">
            <Mark height="14px" />
            <span className="text-[15px] font-semibold text-ink">The guest</span>
          </div>
          <p className={guest}>The room stood up first — floor, then walls — and your furniture settled in where it belongs. Come look at how it sits.</p>
          <p className={you}>What would it feel like without the armchair?</p>
          <div>
            <p className={guest}>Lighter, I think. I’ve taken it out so you can see, and its place is still marked on the floor. Say the word and I’ll bring it back.</p>
            <button
              type="button"
              onClick={toggle}
              className="mt-3 inline-flex h-9 cursor-pointer items-center gap-2 rounded-full bg-surface px-3.5 text-sm font-medium text-ink ring-1 ring-inset ring-ink/15 transition-colors hover:bg-paper"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path d="M9 14L4 9l5-5" />
                <path d="M4 9h10a6 6 0 0 1 0 12h-3" />
              </svg>
              {chairOut ? "Bring it back" : "Take it out again"}
            </button>
          </div>
          <p className={you}>What’s behind the bookcase?</p>
          <p className={guest}>I can’t see behind it; the scan only reached its front. Move it out, walk the room again, and I’ll know.</p>
          {/* A picture of the composer, not a control: nothing here listens. */}
          <div aria-hidden className="mt-auto flex items-center gap-2 rounded-full py-1.5 pl-[18px] pr-1.5 ring-1 ring-inset ring-ink/15">
            <span className="flex-1 text-base text-[#5b6673]">Ask about this room</span>
            <span className="grid h-10 w-10 place-items-center rounded-full bg-ink text-white">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 19V5" />
                <path d="M6 11l6-6 6 6" />
              </svg>
            </span>
          </div>
        </div>
        <div className="relative min-h-[460px] overflow-hidden rounded-[28px] bg-parchment md:min-h-[620px]">
          <SampleRoom
            ref={room}
            label="The sample room with the armchair taken out and its place marked on the floor"
            view={3}
            labels={false}
            removed={["armchair"]}
            fit={1.12}
            className="absolute inset-0"
          />
        </div>
      </div>
    </section>
  );
}

const PROMISES = [
  { title: "Nothing in your room is generated.", body: "Every wall and every piece comes from your own scan." },
  { title: "No feed and no strangers.", body: "Your rooms aren’t public, and there’s nothing to scroll." },
  { title: "Leave whenever you like.", body: "Delete your account, and every room goes with it." },
] as const;

const QUESTIONS = [
  { q: "Which iPhone do I need?", a: "Any iPhone works. Pro models measure with LiDAR, so they give the most faithful rooms." },
  { q: "How long does it take?", a: "About two minutes to walk the room. Rebuilding it takes longer, so you’re free to close the page and come back." },
  { q: "Is there an Android app?", a: "Not yet. For now the scan needs an iPhone." },
] as const;

function Dusk() {
  return (
    <div className="bg-dusk text-on-dusk">
      <section id="privacy" className="mx-auto max-w-[1280px] px-6 pb-20 pt-24 sm:px-10 md:pb-28 md:pt-36">
        <h2 className={`${H2} mb-14 text-on-dusk md:mb-16`}>Your rooms stay yours.</h2>
        <div className="grid gap-10 md:grid-cols-3">
          {PROMISES.map((p) => (
            <div key={p.title} className="border-t border-on-dusk/15 pt-[26px]">
              <p className="mb-3 font-serif text-[30px] leading-[1.15] tracking-[-0.01em] text-on-dusk">{p.title}</p>
              <p className="text-[17px] leading-[1.55] text-on-dusk-2">{p.body}</p>
            </div>
          ))}
        </div>
        <a href="/privacy" className="mt-10 inline-block font-semibold text-on-dusk underline underline-offset-[5px]">
          Read the privacy policy
        </a>
      </section>

      <section className="mx-auto max-w-[1280px] px-6 pb-24 pt-6 sm:px-10 md:pb-36 md:pt-14">
        <div className="grid items-start gap-10 md:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] md:gap-24">
          <h2 className="font-serif text-[clamp(2.25rem,3.6vw,3.15rem)] font-light leading-[1.05] tracking-[-0.025em] text-on-dusk">Before you start</h2>
          <dl>
            {QUESTIONS.map((x, i) => (
              <div key={x.q} className={`border-t border-on-dusk/15 py-6 ${i === QUESTIONS.length - 1 ? "border-b" : ""}`}>
                <dt className="font-serif text-[25px] leading-[1.25] text-on-dusk">{x.q}</dt>
                <dd className="mt-2.5 text-[17px] leading-[1.55] text-on-dusk-2">{x.a}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <section id="start" className="px-3 pb-6 sm:px-6">
        <div className="relative mx-auto flex max-w-[1392px] flex-col-reverse md:block">
          <div className="relative h-[460px] overflow-hidden rounded-[32px] bg-[#121c27] md:h-[700px]">
            <SampleRoom
              label="The sample room in the evening, lit by its lamps"
              mode="night"
              view={0}
              shift={0.15}
              fit={0.92}
              labels={false}
              className="absolute inset-0"
            />
          </div>
          <div className="px-3 pb-10 pt-4 md:pointer-events-none md:absolute md:left-16 md:top-20 md:max-w-[480px] md:p-0">
            <h2 className="font-serif text-[clamp(3rem,5.6vw,5.1rem)] font-light leading-[0.98] tracking-[-0.035em] text-on-dusk">
              Start with the room you’re sitting in.
            </h2>
            <div className="pointer-events-auto mt-9">
              <PillLink href="/new" variant="cream" className="!inline-flex items-center gap-2.5 !px-[26px] !py-4 !text-base">
                Scan your first room
                <Arrow />
              </PillLink>
            </div>
            <p className="mt-[22px] text-base leading-normal text-on-dusk-2">Works on any iPhone. Pro models give the best scans.</p>
          </div>
        </div>
      </section>
    </div>
  );
}

export default function Landing() {
  return (
    <>
      <Hero />
      <Manifesto />
      <HowItWorks />
      <GuestSection />
      <Dusk />
    </>
  );
}
