"use client";

/**
 * Landing — one claim, one image, one action (design §1). The thesis in
 * serif, "Scan your first room" as the action, and — as the only image —
 * a real room measuring itself.
 *
 * THE HERO IS THE REVEAL, NOT A ROOM (decision 0122). What plays here is
 * the first two movements of the reveal choreography against a real
 * capture's GEOMETRY: the measured boundary drawing itself, then the
 * surfaces materializing in place. No object splats — the reasoning, and
 * the ?hero=b taste probe, live in lib/heroRoom. The copy lands in the
 * quiet beat the score already provides; HeroRoom guarantees that signal
 * arrives even when the room cannot play at all.
 *
 * A returning visitor — anyone whose scene list isn't empty — never sees
 * the pitch: the guest greets them and points at their newest room. A
 * localStorage hint ("did the list have rooms last time?") chooses what
 * to render while this visit's list is still loading, so returning
 * visitors don't get a flash of marketing before the greeting.
 *
 * Dev escape: ?pitch=1 forces the pitch in non-live modes (mock always
 * has rooms, which would otherwise make the pitch unreachable).
 */

import { motion } from "motion/react";
import { useEffect, useState, useSyncExternalStore } from "react";

import HeroRoom from "@/components/HeroRoom";
import { PillLink } from "@/components/ui/spring";
import { GuestLine } from "@/components/ui/voice";
import { apiMode, getApiClient } from "@/lib/api";
import type { SceneSummary } from "@/lib/api/types";
import { heroVariant } from "@/lib/heroRoom";
import { statusMeta } from "@/lib/status";

const EASE = [0.22, 1, 0.36, 1] as const;
const HAS_ROOMS_KEY = "thegoodguest:has-rooms";
const emptySubscribe = () => () => {};

/** Shared load-entrance: rise + fade, staggered by `order`. */
function enter(order: number) {
  return {
    initial: { opacity: 0, y: 20 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.7, ease: EASE, delay: 0.1 + order * 0.12 },
  };
}

/** The pitch copy's entrance, held until the room has settled. `order`
 * keeps the same stagger the greeting uses; `landed` is the gate. */
function land(order: number, landed: boolean) {
  return {
    initial: { opacity: 0, y: 20 },
    animate: landed ? { opacity: 1, y: 0 } : { opacity: 0, y: 20 },
    transition: { duration: 0.7, ease: EASE, delay: landed ? order * 0.12 : 0 },
  };
}

type HomeState =
  | { phase: "deciding" }
  | { phase: "pitch" }
  | { phase: "returning"; latest: SceneSummary };

/** The greeting is grounded in the newest room's real state — nothing
 * observed, nothing promised. */
function greetingFor(latest: SceneSummary): {
  line: string;
  cta: string;
  href: string;
} {
  const day = new Date(latest.created_at).toLocaleDateString(undefined, {
    month: "long",
    day: "numeric",
  });
  const roomHref = `/room?bundle=${latest.bundle_id}`;
  if (latest.status === "ready") {
    return {
      line: `The room from ${day} is as you left it.`,
      cta: "Step back inside",
      href: roomHref,
    };
  }
  if (!statusMeta(latest.status).terminal) {
    return {
      line: `Your newest room is still being rebuilt — it won't be long.`,
      cta: "See how it's coming along",
      href: roomHref,
    };
  }
  return {
    line: "Your rooms are where you left them.",
    cta: "Go to your house",
    href: "/rooms",
  };
}

export default function Home() {
  const [state, setState] = useState<HomeState>({ phase: "deciding" });
  // The room measures itself first; the copy lands in the beat after.
  const [landed, setLanded] = useState(false);
  const variant = useSyncExternalStore(
    emptySubscribe,
    () => heroVariant(window.location.search),
    () => "a" as const,
  );

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
        setState(
          scenes.length > 0
            ? { phase: "returning", latest: scenes[0] }
            : { phase: "pitch" },
        );
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
    const greeting = greetingFor(effective.latest);
    return (
      <section className="mx-auto flex min-h-[80vh] max-w-3xl flex-col items-start justify-center px-6">
        <motion.div {...enter(0)}>
          <GuestLine className="text-[clamp(1.6rem,2.6vw,2.1rem)] leading-[1.4]">
            Welcome back. {greeting.line}
          </GuestLine>
        </motion.div>
        <motion.div {...enter(1)} className="mt-10 flex items-center gap-4">
          <PillLink href={greeting.href} className="!px-7 !py-3">
            {greeting.cta}
          </PillLink>
          {greeting.href !== "/rooms" && (
            <PillLink href="/rooms" variant="quiet">
              Your house
            </PillLink>
          )}
        </motion.div>
      </section>
    );
  }

  return (
    <section className="mx-auto grid max-w-6xl gap-10 px-6 pb-16 pt-14 lg:min-h-[calc(100vh-3.5rem)] lg:grid-cols-[minmax(0,42fr)_minmax(0,58fr)] lg:grid-rows-[minmax(0,1fr)] lg:gap-8 lg:pb-8">
      {/* On one column the room goes first: it is the hero, and the copy
          lands under it when the room has settled. */}
      <div className="order-2 flex flex-col justify-center lg:order-1 lg:pr-6">
        <motion.h1
          {...land(0, landed)}
          className="max-w-2xl text-balance font-serif text-[clamp(2.1rem,3.4vw,2.85rem)] font-normal leading-[1.24] tracking-[-0.01em]"
        >
          Every home contains a version of itself its owner has never seen.
        </motion.h1>
        <motion.p
          {...land(1, landed)}
          className="mt-6 max-w-[430px] text-pretty text-base leading-relaxed text-ink/70"
        >
          Scan a room with your phone. Meet it again on your desk — real, in
          3D, exactly as you live in it — with a guest who understands it and
          talks it through with you.
        </motion.p>
        <motion.div
          {...land(2, landed)}
          className="mt-9 flex flex-wrap items-center gap-3"
        >
          <PillLink href="/new" className="!px-7 !py-3">
            Scan your first room
          </PillLink>
        </motion.div>
        <motion.p {...land(3, landed)} className="mt-7 text-xs text-ink/45">
          No photos generated. No feed. Your rooms are yours.
        </motion.p>
      </div>

      {/* Deliberately NOT inside a motion fade: the stage is the page's
          first frame. Fading it in would leave a landing page that is
          briefly blank in both columns — copy not landed, stage not yet
          arrived — which reads as broken rather than as a room about to
          measure itself. The room's own arrival is SplatViewer's job. */}
      <div className="order-1 lg:order-2 lg:my-2">
        <HeroRoom
          variant={variant}
          onSettled={() => setLanded(true)}
          className="lg:h-full"
        />
      </div>
    </section>
  );
}
