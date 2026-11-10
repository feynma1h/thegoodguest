"use client";

/**
 * Landing. A first-time visitor gets components/Landing.tsx (decision 0361,
 * which supersedes 0122's one-screen reveal hero): the pitch told around a
 * sample room they can turn in their hands. Its words never wait on the
 * renderer — a page whose claim is held behind WebGL reads as slow.
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

import Landing from "@/components/Landing";
import { PillLink } from "@/components/ui/spring";
import { GuestLine } from "@/components/ui/voice";
import { apiMode, getApiClient } from "@/lib/api";
import type { SceneSummary } from "@/lib/api/types";
import { statusMeta } from "@/lib/status";

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

  return <Landing />;
}
