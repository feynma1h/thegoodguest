/**
 * The capture path is deliberately one screen: capture happens in the iOS
 * app only (see CLAUDE.md "What we're building"); the web is for
 * everything after.
 */

export default function CapturePage() {
  return (
    <div className="flex flex-col items-center py-24 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-zinc-900 ring-1 ring-zinc-800">
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.5}
          className="h-8 w-8 text-sky-400"
          aria-hidden
        >
          <rect x="7" y="2.5" width="10" height="19" rx="2.5" />
          <circle cx="12" cy="18" r="0.9" fill="currentColor" stroke="none" />
        </svg>
      </div>
      <h1 className="mt-8 text-3xl font-semibold tracking-tight">
        Open the iOS app
      </h1>
      <p className="mt-4 max-w-sm text-pretty text-zinc-400">
        Rooms are captured with the RoomStudio app on iPhone — it uses the
        camera, motion sensors, and LiDAR to measure your space precisely.
        Your scene appears here automatically once the upload finishes.
      </p>
    </div>
  );
}
