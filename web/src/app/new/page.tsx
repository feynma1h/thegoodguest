/**
 * Starting a new room is deliberately one screen: the scan happens in the
 * iOS app (camera + motion + LiDAR measure the space; the web can't), and
 * the room appears in /rooms on its own once the upload lands.
 */

export default function NewRoomPage() {
  return (
    <div className="mx-auto flex max-w-3xl flex-col items-center px-6 py-24 text-center">
      <p className="font-mono text-[11px] uppercase tracking-[0.35em] text-zinc-500">
        New room
      </p>
      <h1 className="mt-6 max-w-xl text-balance font-serif text-4xl font-light leading-tight tracking-tight sm:text-5xl">
        It starts with a slow walk around the room.
      </h1>
      <p className="mt-6 max-w-md text-pretty leading-relaxed text-zinc-400">
        Open the iOS app and scan the space — about a minute. Your iPhone
        measures what a photo can only guess at: true distances, depth, and
        where every object actually stands. The room appears here on its own
        when the scan lands.
      </p>

      <div className="mt-14 grid w-full gap-4 sm:grid-cols-3">
        {[
          { n: "01", text: "Open the iOS app on your iPhone" },
          { n: "02", text: "Walk the room slowly, corners included" },
          { n: "03", text: "That's it — analysis starts on its own" },
        ].map((step) => (
          <div
            key={step.n}
            className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-6 text-left"
          >
            <p className="font-mono text-xs tracking-widest text-accent-soft">{step.n}</p>
            <p className="mt-3 text-sm leading-relaxed text-zinc-300">{step.text}</p>
          </div>
        ))}
      </div>

      <p className="mt-12 font-mono text-[10px] uppercase tracking-widest text-zinc-600">
        LiDAR-equipped iPhones give the most faithful rooms
      </p>
    </div>
  );
}
