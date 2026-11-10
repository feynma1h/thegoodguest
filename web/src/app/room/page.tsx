"use client";

/**
 * A single room: /room?bundle=<bundle_id>. Query-param routing because
 * the static export cannot prerender unknown dynamic path segments
 * (useSearchParams requires the Suspense boundary below during
 * prerender).
 *
 * The room page is immersive — the global nav stands down (SiteNav
 * returns null here) and the page carries its own floating chrome. One
 * governing rule (design §0): this page is a conversation happening in
 * a room; everything else is furniture. Every state sits on dusk
 * (decision 0361), so moving from the wait to the room never flashes
 * daylight. The guest's lines are template narration grounded in real
 * state (lib/voice).
 *
 * States: the Wait (§3 — narrated arrival, real 10s polling, never a
 * progress bar), the partial failure (§8 — honest about missing files),
 * the terminal failure (§8 — a next step, never a stack trace), and the
 * room itself (RoomStage: threshold → reveal → stage 1).
 */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import RoomStage from "@/components/RoomStage";
import SignInPanel from "@/components/SignInPanel";
import { PillButton, PillLink } from "@/components/ui/spring";
import { GuestLine } from "@/components/ui/voice";
import { getApiClient } from "@/lib/api";
import { ApiError } from "@/lib/api/client";
import type { SceneSummary } from "@/lib/api/types";
import { floorAreaText } from "@/lib/card/layout";
import type { RoomMeasure } from "@/lib/card/measure";
import { statusMeta } from "@/lib/status";
import {
  agoPhrase,
  capitalize,
  minutesSince,
  roomTitle,
  smallCount,
  waitNarration,
} from "@/lib/voice";

type Result =
  | { forBundle: string; phase: "error"; message: string }
  | { forBundle: string; phase: "signed-out" }
  | { forBundle: string; phase: "ready"; scene: SceneSummary };

/** The room's top bar (decision 0361): the way back to the house, then the
 * room's name in the display face with one line under it — what state it is
 * in, or its measured floor. It carries neither the mark nor the wordmark:
 * the guest's rail holds the mark, and the name never sits beside it.
 * `railGap` keeps it clear of the conversation rail on wide screens. */
function RoomChrome({
  title,
  subtitle,
  measured = false,
  right,
  railGap = false,
}: {
  title: string;
  subtitle?: string | null;
  /** The subtitle is a measurement, so it takes the measurement face. */
  measured?: boolean;
  right?: React.ReactNode;
  railGap?: boolean;
}) {
  return (
    <header
      className={`pointer-events-none absolute inset-x-0 top-0 z-30 flex items-center justify-between gap-4 px-5 py-4 sm:px-7 sm:py-[22px] ${
        railGap ? "lg:right-[460px]" : ""
      }`}
    >
      <div className="flex min-w-0 items-center gap-[18px]">
        <Link
          href="/rooms"
          className="pointer-events-auto inline-flex items-center gap-1.5 whitespace-nowrap text-sm text-on-dusk-2 transition-colors hover:text-on-dusk"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M15 6l-6 6 6 6" />
          </svg>
          Your house
        </Link>
        {title && (
          <>
            {/* On a phone the name shows only when nothing sits beside it. */}
            <span aria-hidden className={`h-[22px] w-px bg-on-dusk/15 ${right ? "hidden sm:block" : ""}`} />
            <div className={`min-w-0 ${right ? "hidden sm:block" : ""}`}>
              <h1 className="truncate font-serif text-2xl leading-[1.15] text-on-dusk">
                {capitalize(title)}
              </h1>
              {subtitle && (
                <p
                  className={`mt-[3px] text-on-dusk-2 ${
                    measured ? "font-mono text-[12.5px]" : "text-[13px]"
                  }`}
                >
                  {subtitle}
                </p>
              )}
            </div>
          </>
        )}
      </div>
      {right && <div className="pointer-events-auto">{right}</div>}
    </header>
  );
}

/** "Captured at 1:38 pm" — the capture moment is real data. The lamplight
 * dot is light, never ornament. */
function CapturedChip({ createdAt }: { createdAt: string }) {
  const time = new Date(createdAt).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
  return (
    <span className="flex items-center gap-2 whitespace-nowrap rounded-full bg-dusk-3 px-3.5 py-2 text-[13px] text-on-dusk-2">
      <span aria-hidden className="h-2 w-2 shrink-0 rounded-full bg-sun" />
      Captured at {time}
    </span>
  );
}

/** The dusk ground every non-ready state shares: chrome on top, one centred
 * column of words. */
function DuskPage({
  chrome,
  center = false,
  children,
}: {
  chrome: React.ReactNode;
  center?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="relative flex min-h-dvh flex-col overflow-hidden bg-dusk text-on-dusk">
      {chrome}
      <div className="relative flex flex-1 items-center justify-center px-6 pb-16 pt-28">
        <div className={`w-full max-w-[640px] ${center ? "text-center" : ""}`}>{children}</div>
      </div>
    </div>
  );
}

const LINE = "text-[clamp(24px,2.6vw,32px)] leading-[1.32] tracking-[-0.01em]";

/** The scan's reference, for anyone who has to ask about it. Shortened:
 * the first eight characters are enough to find it, and read as a reference
 * rather than a stack trace. */
function ScanReference({ scene }: { scene: SceneSummary }) {
  const ref = (scene.bundle_id ?? scene.scene_id).slice(0, 8);
  return (
    <p className="mt-10 border-t border-on-dusk/10 pt-[18px] text-[13px] text-on-dusk-2">
      Scan reference <span className="font-mono">{ref}</span>
    </p>
  );
}

/** §3 — the wait. Progress is narrated as arrival; the lamplight is
 * atmosphere, never a percentage. Polling (page-level) is the truth behind
 * "this page keeps watch". */
function WaitRoom({ scene }: { scene: SceneSummary }) {
  const queued = scene.status === "queued";
  const narration = waitNarration(
    queued ? "queued" : "processing",
    minutesSince(scene.created_at),
  );
  return (
    <DuskPage
      center
      chrome={<RoomChrome title="a new room" subtitle={queued ? "In line" : "Being rebuilt"} />}
    >
      <span
        aria-hidden
        className="breathe pointer-events-none absolute left-1/2 top-[44%] h-[440px] w-[440px] -translate-x-1/2 -translate-y-1/2 rounded-full"
        style={{
          background:
            "radial-gradient(circle, rgba(240,178,106,0.30) 0%, rgba(240,178,106,0.08) 40%, rgba(240,178,106,0) 70%)",
        }}
      />
      <GuestLine tone="cream" className={`relative ${LINE} sm:text-[clamp(26px,2.8vw,34px)]`}>
        {narration}
      </GuestLine>
      <p className="relative mt-[26px] text-[15px] leading-normal text-on-dusk-2">
        Arrived {agoPhrase(scene.created_at)}. You can close this page; the
        room will be waiting in your house.
      </p>
    </DuskPage>
  );
}

/** §8, recoverable — part of the scan never arrived. The claim matches
 * what iOS actually does: reopening the app resumes unfinished uploads. */
function PartialRoom({ scene }: { scene: SceneSummary }) {
  const missing = scene.missing_paths?.length ?? 0;
  const pieces =
    missing === 1 ? "one piece" : missing > 1 ? `${smallCount(missing)} pieces` : "part";
  return (
    <DuskPage
      chrome={<RoomChrome title={roomTitle(scene.created_at)} subtitle="Partly arrived" />}
    >
      <svg width="120" height="88" viewBox="0 0 120 88" aria-hidden className="mb-8 block">
        <path d="M4 4 H116 V84 H4 Z" fill="none" stroke="#a7b2bf" strokeWidth="2" strokeDasharray="9 8" />
      </svg>
      <GuestLine tone="cream" className={LINE}>
        Most of the room made the trip, but {pieces} of the scan never arrived.
        Nothing is lost — open the app on your iPhone and it picks up where it
        left off.
      </GuestLine>
      <p className="mt-[26px] text-[15px] text-on-dusk-2">
        This page updates on its own when the rest lands.
      </p>
      <ScanReference scene={scene} />
    </DuskPage>
  );
}

/** §8, terminal — honest words, one concrete next step, no stack trace. */
function TerminalRoom({ scene }: { scene: SceneSummary }) {
  const line = `${
    scene.status === "failed_invalid"
      ? "I’m sorry — this scan arrived in a form I can’t read, and I’d rather admit that than show you something false."
      : "I’m sorry — the scan didn’t survive the trip, and there’s nothing here I could honestly show you."
  } It’s not something you did. When you’re near the room again, let’s try one more pass — slower is better.`;
  return (
    <DuskPage
      chrome={<RoomChrome title={roomTitle(scene.created_at)} subtitle="Didn’t make it" />}
    >
      <GuestLine tone="cream" className={LINE}>
        {line}
      </GuestLine>
      <div className="mt-9 flex flex-wrap items-center gap-3">
        <PillLink href="/new" variant="cream" size="lg">
          Scan it again
        </PillLink>
        <PillLink href="/rooms" variant="creamGhost" size="lg">
          Your house
        </PillLink>
      </div>
      <ScanReference scene={scene} />
    </DuskPage>
  );
}

function ReadyRoom({ scene }: { scene: SceneSummary }) {
  const [area, setArea] = useState<string | null>(null);
  const onMeasure = useCallback(
    (measure: RoomMeasure | null) => setArea(measure ? floorAreaText(measure) : null),
    [],
  );
  return (
    <div className="relative min-h-dvh bg-dusk">
      <RoomStage
        key={scene.scene_id}
        sceneId={scene.scene_id}
        status={scene.status}
        createdAt={scene.created_at}
        onMeasure={onMeasure}
      />
      <RoomChrome
        title={roomTitle(scene.created_at)}
        subtitle={area}
        measured
        right={<CapturedChip createdAt={scene.created_at} />}
        railGap
      />
    </div>
  );
}

function RoomDetail() {
  const bundleId = useSearchParams().get("bundle");
  const [result, setResult] = useState<Result | null>(null);

  const state: Result | { phase: "loading" } | { phase: "missing" } = !bundleId
    ? { phase: "missing" }
    : result && result.forBundle === bundleId
      ? result
      : { phase: "loading" };

  useEffect(() => {
    if (!bundleId) return;
    let cancelled = false;
    let timer: number | undefined;
    // Poll while the room is in flight so "this page keeps watch" is
    // actually true; stops on terminal states.
    const load = () => {
      getApiClient()
        .getSceneByBundle(bundleId)
        .then((scene) => {
          if (cancelled) return;
          setResult({ forBundle: bundleId, phase: "ready", scene });
          if (!statusMeta(scene.status).terminal) {
            timer = window.setTimeout(load, 10_000);
          }
        })
        .catch((exc: unknown) => {
          if (cancelled) return;
          // no_local_token = live mode, nobody signed in (decision 0051).
          if (exc instanceof ApiError && exc.code === "no_local_token") {
            setResult({ forBundle: bundleId, phase: "signed-out" });
            return;
          }
          const message =
            exc instanceof ApiError ? exc.message : "Could not reach the server.";
          setResult({ forBundle: bundleId, phase: "error", message });
        });
    };
    load();
    return () => {
      cancelled = true;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [bundleId]);

  if (state.phase === "signed-out") {
    return (
      <DuskPage chrome={<RoomChrome title="" />}>
        <GuestLine tone="cream" className={LINE}>
          This room belongs to an account. Sign in with the one from your
          iPhone and I&rsquo;ll open it for you.
        </GuestLine>
        <div className="mt-9 max-w-sm">
          <SignInPanel tone="dark" />
        </div>
      </DuskPage>
    );
  }

  if (state.phase === "missing" || state.phase === "error") {
    return (
      <DuskPage chrome={<RoomChrome title="" />}>
        {state.phase === "missing" ? (
          <>
            <GuestLine tone="cream" className={LINE}>
              No room is named in this address, so there&rsquo;s nothing for me
              to open.
            </GuestLine>
            <div className="mt-9">
              <PillLink href="/rooms" variant="cream" size="lg">
                Your house
              </PillLink>
            </div>
          </>
        ) : (
          <>
            <GuestLine tone="cream" className={LINE}>
              I couldn&rsquo;t open this room just now. It&rsquo;s still there;
              this is only the connection.
            </GuestLine>
            <p className="mt-[26px] text-[15px] text-on-dusk-2">{state.message}</p>
            <div className="mt-9 flex flex-wrap gap-3">
              <PillButton
                onClick={() => window.location.reload()}
                variant="cream"
                size="lg"
              >
                Try again
              </PillButton>
              <PillLink href="/rooms" variant="creamGhost" size="lg">
                Your house
              </PillLink>
            </div>
          </>
        )}
      </DuskPage>
    );
  }

  if (state.phase === "loading") {
    return <div className="min-h-dvh bg-dusk" aria-hidden />;
  }

  const { scene } = state;

  if (scene.status === "ready") {
    return <ReadyRoom scene={scene} />;
  }
  if (scene.status === "failed" || scene.status === "failed_invalid") {
    return <TerminalRoom scene={scene} />;
  }
  if (scene.status === "failed_incomplete") {
    return <PartialRoom scene={scene} />;
  }
  return <WaitRoom scene={scene} />;
}

export default function RoomPage() {
  return (
    <Suspense fallback={<div className="min-h-dvh bg-dusk" aria-hidden />}>
      <RoomDetail />
    </Suspense>
  );
}
