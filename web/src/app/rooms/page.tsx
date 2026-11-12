"use client";

/**
 * Your house (decision 0361): GET /scenes as sibling rooms (design §9 — no
 * floor plan of the house, no map; each room its own conversation). Each
 * card shows the room as it is right now — its measured plan once it is
 * ready. Client-side fetch: the static export has no server, so data loads
 * after hydration through the ApiClient (mock fixtures or live api-public).
 *
 * Signed out (live mode, nobody here — decision 0051) is an invitation, not
 * an error: the page becomes the sign-in, because the house is where a
 * person's rooms follow their account.
 */

import { motion } from "motion/react";
import { useEffect, useState } from "react";

import RoomCard from "@/components/RoomCard";
import SignInPanel from "@/components/SignInPanel";
import { ArrowIcon, PillButton, PillLink } from "@/components/ui/spring";
import { getApiClient } from "@/lib/api";
import { ApiError } from "@/lib/api/client";
import type { SceneSummary } from "@/lib/api/types";
import { capitalize, smallCount } from "@/lib/voice";

type State =
  | { phase: "loading" }
  | { phase: "signed-out" }
  | { phase: "error"; message: string }
  | { phase: "ready"; scenes: SceneSummary[] };

const EASE = [0.22, 1, 0.36, 1] as const;

function Title({ children }: { children: React.ReactNode }) {
  return (
    <h1 className="font-serif text-[clamp(44px,5vw,64px)] font-light leading-none tracking-[-0.03em] text-ink">
      {children}
    </h1>
  );
}

export default function RoomsPage() {
  const [state, setState] = useState<State>({ phase: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    getApiClient()
      .listScenes()
      .then((scenes) => !cancelled && setState({ phase: "ready", scenes }))
      .catch((exc: unknown) => {
        if (cancelled) return;
        // no_local_token = live mode, nobody signed in (decision 0051).
        if (exc instanceof ApiError && exc.code === "no_local_token") {
          setState({ phase: "signed-out" });
          return;
        }
        const message =
          exc instanceof ApiError ? exc.message : "Could not reach the server.";
        setState({ phase: "error", message });
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  if (state.phase === "signed-out") {
    return (
      <div className="mx-auto flex max-w-[1280px] justify-center px-4 pb-24 pt-12 sm:px-10 sm:pt-[72px]">
        <section
          aria-labelledby="signin-h"
          className="w-full max-w-[520px] rounded-[28px] bg-white p-7 shadow-[0_1px_0_rgba(18,26,35,0.04),0_18px_44px_rgba(18,26,35,0.07)] sm:p-12"
        >
          <h1
            id="signin-h"
            className="font-serif text-[44px] font-light leading-[1.05] tracking-[-0.025em] text-ink"
          >
            Your house
          </h1>
          <p className="mt-[18px] font-serif text-[21px] italic leading-[1.45] text-ink">
            Your rooms are signed in on your iPhone. Sign in here with the same
            account, and the house follows.
          </p>
          <div className="mt-8">
            <SignInPanel />
          </div>
          <p className="mt-6 text-[14px] leading-normal text-ink-2">
            No rooms yet? Scan one with your iPhone first. Signing in there and
            here is what joins them up.
          </p>
        </section>
      </div>
    );
  }

  const scenes = state.phase === "ready" ? state.scenes : null;
  const count = scenes?.length ?? 0;

  return (
    <div className="mx-auto max-w-[1280px] px-4 pb-24 pt-10 sm:px-10 sm:pt-14">
      <div className="mb-9 sm:mb-11">
        <Title>Your house</Title>
        {scenes && count > 0 && (
          <p className="mt-3.5 text-[17px] text-ink-2">
            {count === 1
              ? "One room so far. It keeps its own conversation."
              : `${capitalize(smallCount(count))} rooms. Each one keeps its own conversation.`}
          </p>
        )}
      </div>

      {state.phase === "loading" && (
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3" aria-label="Looking for your rooms">
          {[0, 1, 2].map((i) => (
            <div key={i} className="overflow-hidden rounded-3xl bg-white shadow-lift" style={{ opacity: 1 - i * 0.22 }}>
              <div className="breathe h-[250px] bg-[#eef1f4]" />
              <div className="px-[22px] pb-6 pt-5">
                <div className="h-5 w-3/5 rounded-full bg-parchment" />
                <div className="mt-3 h-3.5 w-2/5 rounded-full bg-parchment" />
              </div>
            </div>
          ))}
        </div>
      )}

      {state.phase === "error" && (
        <div className="max-w-xl rounded-3xl bg-white p-8 shadow-lift">
          <p className="text-[17px] font-semibold text-ink">I couldn&rsquo;t reach your house just now.</p>
          <p className="mt-2 text-[15px] leading-relaxed text-ink-2">
            Your rooms are safe; this is only the connection. {state.message}
          </p>
          <PillButton variant="ghost" onClick={() => {
            setState({ phase: "loading" });
            setAttempt((n) => n + 1);
          }} className="mt-6">
            Try again
          </PillButton>
        </div>
      )}

      {scenes && count === 0 && (
        <div className="flex min-h-[420px] flex-col items-start justify-center rounded-[28px] border-[1.5px] border-dashed border-ink/[0.18] px-7 py-12 sm:px-16 sm:py-14">
          <p className="max-w-[24ch] font-serif text-[clamp(28px,3vw,36px)] italic leading-[1.25] tracking-[-0.01em] text-ink">
            One room is a conversation. A house is a life — whenever you&rsquo;re ready.
          </p>
          <p className="mb-8 mt-5 max-w-xl text-[17px] leading-[1.55] text-ink-2">
            Scan a room with your iPhone and it appears here, ready to step
            into. Every room you scan keeps its own conversation.
          </p>
          <PillLink href="/new" size="lg">
            Scan your first room
            <ArrowIcon />
          </PillLink>
        </div>
      )}

      {scenes && count > 0 && (
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {scenes.map((scene, i) => (
            <motion.div
              key={scene.scene_id}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, ease: EASE, delay: i * 0.06 }}
            >
              <RoomCard scene={scene} />
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}
