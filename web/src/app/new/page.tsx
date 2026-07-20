/**
 * Starting a new room is deliberately one screen: the scan happens in the
 * iOS app (camera + motion + LiDAR measure the space; the web can't), and
 * the room appears in /rooms on its own once the upload lands.
 */

export default function NewRoomPage() {
  return (
    <div className="mx-auto flex max-w-3xl flex-col items-center px-6 py-24 text-center">
      <h1 className="max-w-xl text-balance text-4xl font-semibold leading-tight tracking-[-0.02em] sm:text-5xl">
        It starts with a slow walk around the room.
      </h1>
      <p className="mt-6 max-w-md text-pretty leading-relaxed text-zinc-400">
        Open the iOS app and scan the space — about a minute. Your iPhone
        measures what a photo can only guess at: true distances, depth, and
        where every object actually stands. The room appears here on its own
        when the scan lands.
      </p>

      <div className="mt-16 grid w-full gap-10 text-left sm:grid-cols-3">
        {[
          { n: "01", text: "Open the iOS app on your iPhone" },
          { n: "02", text: "Walk the room slowly, corners included" },
          { n: "03", text: "That's it — analysis starts on its own" },
        ].map((step) => (
          <div key={step.n}>
            <p className="text-xs font-medium text-zinc-600">{step.n}</p>
            <p className="mt-3 text-sm leading-relaxed text-zinc-300">{step.text}</p>
          </div>
        ))}
      </div>

      <p className="mt-16 text-xs text-zinc-600">
        LiDAR-equipped iPhones give the most faithful rooms.
      </p>
    </div>
  );
}
