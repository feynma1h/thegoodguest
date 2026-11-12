"use client";

/**
 * Landing. A first-time visitor gets components/Landing.tsx (decision 0361,
 * which supersedes 0122's one-screen reveal hero): the pitch told around a
 * sample room they can turn in their hands. Its words never wait on the
 * renderer — a page whose claim is held behind WebGL reads as slow.
 *
 * A returning visitor — anyone whose scene list isn't empty — never sees
 * the pitch: the guest greets them beside their newest room, drawn as its
 * measured plan (the house's drawing, so the two pages agree). A room that
 * hasn't been opened yet is never shown before its threshold: the stage
 * holds lamplight instead, and the greeting invites them in. A
 * localStorage hint ("did the list have rooms last time?") chooses what to
 * render while this visit's list is still loading, so returning visitors
 * don't get a flash of marketing before the greeting.
 *
 * Dev escape: ?pitch=1 forces the pitch in non-live modes (mock always
 * has rooms, which would otherwise make the pitch unreachable).
 */

import { motion } from "motion/react";
import { useEffect, useState, useSyncExternalStore } from "react";

import Landing from "@/components/Landing";
import PlanFigure from "@/components/PlanFigure";
import { useRoomPlan } from "@/components/RoomCard";
import { ArrowIcon, PillLink } from "@/components/ui/spring";
import { apiMode, getApiClient } from "@/lib/api";
import type { SceneSummary } from "@/lib/api/types";
import { floorAreaText } from "@/lib/card/layout";
import { hasSeenReveal } from "@/lib/seen";
import { statusMeta } from "@/lib/status";
import { capitalize, minutesSince, roomTitle, smallCount, waitNarration } from "@/lib/voice";

const EASE = [0.22, 1, 0.36, 1] as const;
const HAS_ROOMS_KEY = "thegoodguest:has-rooms";
const emptySubscribe = () => () => {};

/** The page's one load-entrance: rise + fade, staggered by `order`. The
 * greeting and the pitch both use it, so whichever a visitor gets arrives
 * the same way and at the same moment. */
function enter(order: number) {
  return {
    initial: { opacity: 0, y: 20 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.7, ease: EASE, delay: 0.1 + order * 0.12 },
  };
}

type HomeState =
  | { phase: "deciding" }
  | { phase: "pitch" }
  | { phase: "returning"; scenes: SceneSummary[] };

function dayOf(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "long", day: "numeric" });
}

/** The greeting is grounded in the newest room's real state — nothing
 * observed, nothing promised. */
function greetingFor(
  latest: SceneSummary,
  seen: boolean,
): { line: string; cta: string; href: string } {
  const roomHref = `/room?bundle=${latest.bundle_id}`;
  if (latest.status === "ready") {
    return seen
      ? {
          line: `The room from ${dayOf(latest.created_at)} is as you left it.`,
          cta: "Step back inside",
          href: roomHref,
        }
      : {
          line: `The room from ${dayOf(latest.created_at)} is ready. Come in when you have a minute.`,
          cta: "Come in",
          href: roomHref,
        };
  }
  if (!statusMeta(latest.status).terminal && latest.status !== "failed_incomplete") {
    return {
      line: "Your newest room is still being rebuilt — it won’t be long.",
      cta: "See how it’s coming along",
      href: roomHref,
    };
  }
  return {
    line: "Your rooms are where you left them.",
    cta: "Go to your house",
    href: "/rooms",
  };
}

/** The stage beside the greeting: lamplight for a room still forming or
 * not yet opened, the newest opened room's measured plan otherwise. */
function Stage({ scenes, latestSeen }: { scenes: SceneSummary[]; latestSeen: boolean }) {
  const latest = scenes[0];
  const inFlight = latest.status === "queued" || latest.status === "processing";
  const unopened = latest.status === "ready" && !latestSeen;
  // The plan shown is the newest room's when it is ready, else the newest
  // ready one's, so a failed scan never empties the stage.
  const shown =
    latest.status === "ready" ? latest : scenes.find((s) => s.status === "ready") ?? null;
  // Lamplight needs no plan, so none is fetched for it.
  const plan = useRoomPlan(inFlight || unopened ? null : shown);

  if (inFlight || unopened) {
    return (
      <div className="relative flex h-[420px] items-end overflow-hidden rounded-[28px] bg-dusk p-8 sm:p-10 lg:h-[600px]">
        <span
          aria-hidden
          className="breathe absolute left-1/2 top-[44%] h-[420px] w-[420px] -translate-x-1/2 -translate-y-1/2 rounded-full"
          style={{
            background:
              "radial-gradient(circle, rgba(240,178,106,0.30) 0%, rgba(240,178,106,0.08) 40%, rgba(240,178,106,0) 70%)",
          }}
        />
        <p className="relative max-w-[26ch] font-serif text-[clamp(22px,2vw,28px)] italic leading-[1.35] text-on-dusk">
          {inFlight
            ? waitNarration(latest.status === "queued" ? "queued" : "processing", minutesSince(latest.created_at))
            : "It holds still until you’re ready."}
        </p>
      </div>
    );
  }

  if (!shown || plan.phase === "none") return null;
  const title = capitalize(roomTitle(shown.created_at));

  return (
    <div className="relative h-[420px] overflow-hidden rounded-[28px] bg-parchment lg:h-[600px]">
      {plan.phase === "drawn" ? (
        <PlanFigure
          measure={plan.measure}
          label={`The measured floor plan of ${roomTitle(shown.created_at)}`}
          className="absolute inset-0 h-full w-full px-6 pb-6 pt-24 sm:px-10"
        />
      ) : (
        <div aria-hidden className="breathe absolute inset-16 rounded-2xl bg-white/50" />
      )}
      <div className="absolute left-[22px] top-[22px] rounded-2xl bg-white px-[17px] pb-3 pt-[13px] shadow-float">
        <p className="font-serif text-[19px] leading-[1.2] text-ink">{title}</p>
        {plan.phase === "drawn" && (
          <p className="mt-1 font-mono text-[12.5px] text-ink-2">{floorAreaText(plan.measure)}</p>
        )}
      </div>
    </div>
  );
}

function Returning({ scenes }: { scenes: SceneSummary[] }) {
  const latest = scenes[0];
  // Only ever rendered after the client fetch resolves, so reading
  // localStorage here cannot disagree with a server render.
  const latestSeen = hasSeenReveal(latest.scene_id);
  const greeting = greetingFor(latest, latestSeen);
  const count = scenes.length;
  const countLine =
    count === 1
      ? `One room in your house, scanned on ${dayOf(latest.created_at)}.`
      : `${capitalize(smallCount(count))} rooms in your house. The newest was scanned on ${dayOf(latest.created_at)}.`;

  return (
    <section className="mx-auto grid min-h-[calc(100dvh-76px)] max-w-[1392px] items-center gap-10 px-6 pb-12 pt-6 sm:px-10 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] lg:gap-14">
      <div>
        <motion.p
          {...enter(0)}
          className="font-serif text-[clamp(32px,3.4vw,48px)] italic leading-[1.18] tracking-[-0.015em] text-ink"
        >
          Welcome back. {greeting.line}
        </motion.p>
        <motion.div {...enter(1)} className="mt-10 flex flex-wrap items-center gap-3.5">
          <PillLink href={greeting.href} size="lg">
            {greeting.cta}
            <ArrowIcon />
          </PillLink>
          {greeting.href !== "/rooms" && (
            <PillLink href="/rooms" variant="ghost" size="lg">
              Your house
            </PillLink>
          )}
        </motion.div>
        <motion.p {...enter(2)} className="mt-7 text-[15px] leading-normal text-ink-2">
          {countLine}
        </motion.p>
      </div>
      <motion.div {...enter(1)}>
        <Stage scenes={scenes} latestSeen={latestSeen} />
      </motion.div>
    </section>
  );
}

export default function Home() {
  const [state, setState] = useState<HomeState>({ phase: "deciding" });

  // What did last visit's list say? Decides what "deciding" looks like.
  const hasRoomsHint = useSyncExternalStore(
    emptySubscribe,
    () => localStorage.getItem(HAS_ROOMS_KEY) === "1",
    () => false,
  );
  // Dev escape, derived not stored: the query never changes in-page.
  const forcedPitch = useSyncExternalStore(
    emptySubscribe,
    () =>
      apiMode() !== "live" &&
      new URLSearchParams(window.location.search).has("pitch"),
    () => false,
  );

  useEffect(() => {
    if (forcedPitch) return;
    let cancelled = false;
    getApiClient()
      .listScenes()
      .then((scenes) => {
        if (cancelled) return;
        localStorage.setItem(HAS_ROOMS_KEY, scenes.length > 0 ? "1" : "0");
        setState(scenes.length > 0 ? { phase: "returning", scenes } : { phase: "pitch" });
      })
      .catch(() => {
        // The landing must never break on a backend hiccup — pitch it is.
        if (!cancelled) setState({ phase: "pitch" });
      });
    return () => {
      cancelled = true;
    };
  }, [forcedPitch]);

  const effective: HomeState = forcedPitch ? { phase: "pitch" } : state;

  // While deciding, a returning visitor sees calm paper (the greeting is
  // about to land); a first-time visitor sees the pitch immediately.
  if (effective.phase === "deciding" && hasRoomsHint) {
    return <div className="min-h-[80vh]" aria-hidden />;
  }

  if (effective.phase === "returning") {
    return <Returning scenes={effective.scenes} />;
  }

  return <Landing />;
}
