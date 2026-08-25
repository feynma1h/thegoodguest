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
 * a room; everything else is furniture. The guest's lines are template
 * narration grounded in real state (lib/voice); on a ready room RoomStage
 * hands the composer to the live conversation surface, and the disabled
 * composer stays behind in the wait and as RoomStage's fallback when the
 * conversation GET fails.
 *
 * States: the Wait (§3 — narrated arrival, real 10s polling, never a
 * progress bar), the partial failure (§8 — honest about missing files),
 * the terminal failure (§8 — dark panel, a next step, never a stack
 * trace), and the room itself (RoomStage: hold → reveal → stage 1).
 */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import SignInPanel from "@/components/SignInPanel";
import RoomStage from "@/components/RoomStage";
import { Mark } from "@/components/Wordmark";
import { PillLink } from "@/components/ui/spring";
import { DisabledComposer, GuestLine } from "@/components/ui/voice";
import { getApiClient } from "@/lib/api";
import { ApiError } from "@/lib/api/client";
import type { SceneSummary } from "@/lib/api/types";
import { statusMeta } from "@/lib/status";
import { elapsedPhrase, minutesSince, roomTitle, waitNarration } from "@/lib/voice";

type Result =
  | { forBundle: string; phase: "error"; message: string }
  | { forBundle: string; phase: "signed-out" }
  | { forBundle: string; phase: "ready"; scene: SceneSummary };

/** Floating chrome shared by every room-page state: the way back, the
 * placeholder wordmark, the room's derived name, and a right-side slot. */
function RoomChrome({
  tone,
  title,
  right,
}: {
  tone: "ink" | "cream";
  title: string;
  right?: React.ReactNode;
}) {
  const dim = tone === "cream" ? "text-paper/55 hover:text-paper" : "text-ink/55 hover:text-ink";
  return (
    <header className="pointer-events-none absolute inset-x-0 top-0 z-30 flex h-14 items-center justify-between px-6">
      <div className="flex items-baseline gap-4">
        <Link
          href="/rooms"
          className={`pointer-events-auto whitespace-nowrap text-xs font-medium transition-colors ${dim}`}
        >
          ← your house
        </Link>
        <Link
          href="/"
          className="pointer-events-auto hidden transition-opacity hover:opacity-70 sm:block"
        >
          <Mark height="20px" tone={tone === "cream" ? "reverse" : "ink"} />
        </Link>
        <span
          className={`hidden font-serif text-[15px] italic sm:inline ${
            tone === "cream" ? "text-paper/85" : "text-ink/85"
          }`}
        >
          {title}
        </span>
      </div>
      {right && <div className="pointer-events-auto">{right}</div>}
    </header>
  );
}

/** "as captured · 1:38 pm" — the capture moment is real data; the sun
 * dial only arrives with lighting simulation. Gold = light, never
 * ornament. */
function CapturedChip({ createdAt }: { createdAt: string }) {
  const time = new Date(createdAt).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
  return (
    <span className="flex items-center gap-2 whitespace-nowrap rounded-full border border-ink/15 bg-paper/90 px-3.5 py-1.5 text-xs text-ink/75">
      <span aria-hidden className="h-2 w-2 shrink-0 rounded-full bg-sun" />
      as captured · {time}
    </span>
  );
}

/** §3 — the wait. Progress is narrated as arrival; the forming stage is
 * atmosphere, never a percentage. Polling (page-level) is the truth
 * behind "this page keeps watch". */
function WaitRoom({ scene }: { scene: SceneSummary }) {
  const narration = waitNarration(
    scene.status === "queued" ? "queued" : "processing",
    minutesSince(scene.created_at),
  );
  return (
    <div className="relative flex min-h-dvh flex-col bg-paper">
      <RoomChrome
        tone="ink"
        title="a new room, being rebuilt"
        right={
          <span className="hidden text-xs text-ink/50 sm:block">
            minutes, not seconds · you can leave — this page keeps watch
          </span>
        }
      />
      <div className="flex flex-1 flex-col items-center justify-center px-6 pt-14">
        <div className="hatch breathe h-56 w-full max-w-lg rounded-xl" aria-hidden />
        <GuestLine className="mt-10 max-w-lg text-center text-[17px]">
          {narration}
        </GuestLine>
        <p className="mt-3 text-xs text-ink/50">{elapsedPhrase(scene.created_at)}</p>
      </div>
      <div className="mx-auto mb-10 w-full max-w-xl px-6">
        <DisabledComposer />
      </div>
    </div>
  );
}

/** §8, recoverable — part of the scan never arrived. The claim matches
 * what iOS actually does: reopening the app resumes unfinished uploads. */
function PartialRoom({ scene }: { scene: SceneSummary }) {
  const missing = scene.missing_paths?.length ?? 0;
  return (
    <div className="relative flex min-h-dvh flex-col bg-paper">
      <RoomChrome tone="ink" title={roomTitle(scene.created_at)} />
      <div className="mx-auto flex max-w-lg flex-1 flex-col items-start justify-center px-6 pt-14">
        <GuestLine className="text-[17px]">
          Most of the room made the trip, but{" "}
          {missing === 1 ? "one piece" : `${missing} pieces`} of the scan
          never arrived. Nothing is lost — reopen the iOS app on your iPhone
          and it picks up where it left off.
        </GuestLine>
        <p className="mt-6 text-xs text-ink/50">
          this page updates on its own when the rest lands
        </p>
        <p className="mt-10 border-t border-ink/10 pt-5 font-mono text-[10px] text-ink/35">
          {scene.bundle_id}
        </p>
      </div>
    </div>
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
    <div className="relative flex min-h-dvh flex-col bg-ink">
      <RoomChrome tone="cream" title={roomTitle(scene.created_at)} />
      <div className="mx-auto flex max-w-lg flex-1 flex-col items-start justify-center px-6 pt-14">
        <GuestLine tone="cream" className="text-[17px]">
          {line}
        </GuestLine>
        <div className="mt-9 flex items-center gap-3">
          <PillLink href="/new" variant="cream">
            Rescan from your phone
          </PillLink>
          <PillLink href="/rooms" variant="creamGhost">
            your house
          </PillLink>
        </div>
        <p className="mt-10 border-t border-paper/10 pt-5 font-mono text-[10px] text-paper/30">
          {scene.bundle_id}
        </p>
      </div>
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
      <div className="relative flex min-h-dvh flex-col bg-paper">
        <RoomChrome tone="ink" title="" />
        <div className="mx-auto flex max-w-lg flex-1 flex-col items-start justify-center px-6 pt-14">
          <GuestLine className="text-[17px]">
            This room belongs to an account. Sign in with the one from your
            iPhone and I&rsquo;ll open it for you.
          </GuestLine>
          <div className="mt-9">
            <SignInPanel />
          </div>
        </div>
      </div>
    );
  }

  if (state.phase === "missing" || state.phase === "error") {
    return (
      <div className="relative flex min-h-dvh flex-col bg-paper">
        <RoomChrome tone="ink" title="" />
        <div className="mx-auto flex max-w-lg flex-1 flex-col items-start justify-center px-6 pt-14">
          {state.phase === "missing" ? (
            <p className="text-ink/70">
              No room selected.{" "}
              <Link href="/rooms" className="text-accent-deep underline underline-offset-4">
                Back to your house
              </Link>
            </p>
          ) : (
            <>
              <p className="text-sm font-medium text-accent-deep">
                Couldn&apos;t open this room
              </p>
              <p className="mt-2 text-sm text-ink/60">{state.message}</p>
            </>
          )}
        </div>
      </div>
    );
  }

  if (state.phase === "loading") {
    return <div className="min-h-dvh bg-paper" aria-hidden />;
  }

  const { scene } = state;

  if (scene.status === "ready") {
    return (
      <div className="relative min-h-dvh bg-[#1c1610]">
        <RoomStage
          key={scene.scene_id}
          sceneId={scene.scene_id}
          status={scene.status}
          createdAt={scene.created_at}
        />
        <RoomChrome
          tone="cream"
          title={roomTitle(scene.created_at)}
          right={<CapturedChip createdAt={scene.created_at} />}
        />
      </div>
    );
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
    <Suspense fallback={<div className="min-h-dvh bg-paper" aria-hidden />}>
      <RoomDetail />
    </Suspense>
  );
}
