<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

## Known toolchain quirks (project-observed)

- The SWC/JSX transform in this Next version drops the leading space of a JSX
  text chunk **when that chunk contains an HTML entity** (`&rsquo;` etc.):
  `{expr} · it&rsquo;s ready` renders as `…in· it's ready`. Plain text with no
  entity is fine.

  The trigger is **not limited to `{expression}` siblings** — it fires after a
  preceding ELEMENT too. Observed 2026-08-08 while writing the legal pages:
  `<strong>Photographs of the room.</strong> The app keeps a still frame
  roughly every 10&nbsp;cm…` rendered as `room.The app keeps`, because the
  chunk after `</strong>` carried a `&nbsp;` further along. The entity does not
  have to be adjacent to the dropped space; anywhere in the same text chunk is
  enough.

  Two workarounds, both in use:
  1. **Avoid entities.** Write the literal character — `’ “ ” × —` and a real
     space instead of `&nbsp;`. ESLint's `react/no-unescaped-entities` only
     forbids ASCII `' " > }`, so typographic characters are fine and read
     better in source. This is what `app/privacy` and `app/terms` do, and it
     removes the trigger class rather than patching each site.
  2. **Fold the phrase into ONE expression** — a template literal with real
     `’` characters (see `RoomCard`'s elapsed line and `TerminalRoom`'s guest
     line). Better when the string is already partly computed.

  Either way: **verify rendered text in a browser, not in source.** This class
  of bug is invisible to eslint, tsc, and the build.
