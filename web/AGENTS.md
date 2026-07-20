<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

## Known toolchain quirks (project-observed)

- The SWC/JSX transform in this Next version drops the leading space of a JSX
  text chunk that follows a `{expression}` **when that chunk contains an HTML
  entity** (`&rsquo;` etc.): `{expr} · it&rsquo;s ready` renders as
  `…in· it's ready`. Plain text after an expression is fine. Workaround: fold
  the whole phrase into ONE expression — a template literal with real `’`
  characters (see `RoomCard`'s elapsed line and `TerminalRoom`'s guest line).
