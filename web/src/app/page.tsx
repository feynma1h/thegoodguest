import Link from "next/link";

export default function Home() {
  return (
    <div className="flex flex-col items-center py-24 text-center">
      <h1 className="max-w-2xl text-balance text-4xl font-semibold tracking-tight sm:text-5xl">
        Your room, captured.
        <span className="block text-zinc-500">Editable anywhere.</span>
      </h1>
      <p className="mt-6 max-w-md text-pretty text-zinc-400">
        Scan a room with the RoomStudio iOS app. Every object becomes a
        photoreal 3D piece you can browse, rearrange, and share — right here
        in your browser.
      </p>
      <div className="mt-10 flex items-center gap-4">
        <Link
          href="/scenes"
          className="rounded-lg bg-sky-500 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-sky-400"
        >
          Browse your scenes
        </Link>
        <Link
          href="/capture"
          className="rounded-lg border border-zinc-700 px-5 py-2.5 text-sm font-medium text-zinc-300 transition hover:border-zinc-500 hover:text-zinc-100"
        >
          Capture a room
        </Link>
      </div>
    </div>
  );
}
