# Hermes TUI — recon for the Melange terminal interface

Read-only recon, 2026-10-16. All claims sourced to files in
`C:\Users\Administrator\AppData\Local\hermes\hermes-agent\` on SHATNER unless
noted. Paths below are relative to that repo root.

## 1. What the TUI is

- A **React + Ink terminal application** written in TypeScript. Not a web
  page, not blessed, not a curses app. The README says it in one line:
  "React + Ink terminal UI for Hermes. TypeScript owns the screen. Python
  owns sessions, tools, model calls, and most command logic."
  (`ui-tui/README.md`)
- Client package: name `hermes-tui`, React 19.2.7, a **forked Ink renderer**
  shipped as a local package `@hermes/ink` (`ui-tui/packages/hermes-ink/`),
  `nanostores` for state, `ink-text-input` for masked/free-text prompts, and
  `unicode-animations` for spinners. (`ui-tui/package.json`)
- Client source: `ui-tui/src/` — entry `src/entry.tsx`, top component
  `src/app.tsx`, logic split across `src/app/*`, components in
  `src/components/*`. Built output the CLI actually runs:
  `ui-tui/dist/entry.js`.

### Launch

- `hermes --tui` from a terminal. The entrypoint exits early if stdin is not
  a TTY. (`ui-tui/README.md`; `ui-tui/src/entry.tsx`)
- Dev mode: `cd ui-tui && npm run dev` (tsx watch); the CLI falls back to
  this when `ui-tui/dist/entry.js` is missing and sources are present.

### Architecture and transport (important: NOT the :8642 gateway)

- The TUI client **spawns its own Python backend as a child process**:
  `python -m tui_gateway.entry` (interpreter from `HERMES_PYTHON`, set by
  the CLI launcher). Client side: `ui-tui/src/gatewayClient.ts`; Python
  side: `tui_gateway/entry.py`, RPC handlers in `tui_gateway/server.py`.
- Transport is **newline-delimited JSON-RPC over the child's stdio**.
  Requests go client → gateway; the gateway can also send server → client
  *requests* (approval, clarify, sudo, secret) that the client answers.
  Events stream as notifications (full table in `ui-tui/README.md`,
  "Event surface"). Malformed stdout lines become `gateway.protocol_error`;
  child stderr is captured into an in-memory ring, never written to the
  terminal.
- So there are two different "gateways" in this estate: the desktop app's
  HTTP/WebSocket gateway on :8642, and the TUI's private stdio gateway in
  `tui_gateway/`. The TUI does not talk to :8642 in its normal local launch.
- Gateway crash recovery: the client respawns and resumes the session with
  a budget of 3 attempts / 60 s (`ui-tui/src/app/gatewayRecovery.ts`).

### The hosted variant running on SHATNER ("hermes-tui-server")

The `hermes-tui-server` process in the process list is **not** the Ink
client. It is a separate hosted front end supervised by
`C:\Users\Administrator\AppData\Local\hermes\Start-Hermes-HostedTui.ps1`
(a 15-second watchdog loop):

- `webtty go hermes-tui` (webtty from `AppData\Roaming\npm\webtty.cmd`)
  hosts the TUI's PTY on **ws://127.0.0.1:2346**; the PTY is created at the
  first client's geometry rather than a fixed size.
- `node C:\Users\Administrator\AppData\Local\hermes\hermes-tui-server6.js`
  listens on **port 9092** (env `HERMES_TUI_PORT` / `HERMES_TUI_HOST`,
  default bind 0.0.0.0). It serves a single HTML page embedding **xterm.js +
  xterm-addon-fit** (assets embedded so clients never depend on a CDN) and
  proxies the browser terminal to the webtty WebSocket.
- Purpose, per the server source comments: reach the real TUI from a
  **Kindle Scribe browser** over Tailscale Funnel. Access is gated by a
  token in `HERMES_HOME\scribe-token` (case-insensitive compare; missing
  token file = every unauthenticated request gets a bare 404, fail
  closed). (`hermes-tui-server6.js`, first ~60 lines)
- Inside the browser you get the genuine Ink TUI rendering into xterm.js;
  the hosted layer adds no UI of its own beyond the terminal surface.
- The Python gateway also has a separate hosted-room subsystem
  (`tui_gateway/hosted_room_*.py`, `methods_*.py`) — multi-member rooms
  over RPC; not the path the desktop or local TUI uses.

## 2. Screen layout (concrete)

The screen is a single-column Ink tree inside an alternate screen
(`ui-tui/src/components/appLayout.tsx`, `app.tsx`). Top to bottom:

1. **Transcript pane** (flex-grows; `ScrollBox` with virtualized history
   rows, or a plain column in native mode). Contents, in order:
   - Intro row at session start: the **Banner** (ASCII logo art + tagline
     from `ui-tui/src/banner.ts`, responsive: full art → compact dashed
     rule with centered tagline → brand text → hidden below 34 columns)
     followed by the **SessionPanel** — session metadata from the
     `session.info` event: model, cwd, MCP servers, skills and toolsets
     (capped lists). (`ui-tui/src/components/branding.tsx`)
   - Message rows (`ui-tui/src/components/messageLine.tsx`): user and
     assistant turns, later user turns separated by a `───` rule. Assistant
     text is rendered from a Markdown subset to Ink components (headings,
     lists, quotes, tables, fenced code, diff coloring, links) unless the
     payload already contains ANSI, which is printed as-is.
     (`ui-tui/src/components/markdown.tsx`, README "Rendering")
   - A **live streaming assistant row** for the in-flight turn (streaming
     text segments, reasoning, active tools) plus a **live activity lane**
     for tool/status activity, so transcript rows stay focused on
     user/assistant turns.
   - A **LiveTodoPanel** rides attached to the latest user-message row
     (turn todo list, collapsible).
2. **Pet pane** (optional): a Petdex mascot floats bottom-right just above
   the status bar; it reserves a right gutter on wide terminals (≥72 cols
   of body) or bottom rows on narrow ones. Renders nothing unless a pet is
   installed and enabled.
3. **Bottom zone** (`NoSelect`, `flexShrink={0}`), rendered in this order:
   - **QueuedMessages** preview — drafts queued while the agent is busy.
   - **GoalBar** — one line when a `/goal` is standing:
     `⊙ goal · 3/20 turns · <title>` (`ui-tui/src/components/goalBar.tsx`).
   - **LiveAgentsPanel** (the "agents dock") — appears automatically above
     the composer **only while subagents are running**: live child counts,
     task names, elapsed time, latest activity. Its row budget shrinks on
     short terminals. (README "Live agents")
   - **StatusRule** (top position variant) — the status line; see below.
   - **AmbientDock `dock-top`** — widget-app surface (see §5).
   - **Composer**: prompt glyph (from the active skin) + the text input
     (`ui-tui/src/components/textInput.tsx`), with the completion list
     when open and a HelpHint line for context keys.
   - **AmbientDock `dock-bottom`** — widget-app surface.
   - **StatusRule** (bottom position variant).
   - `/statusbar` (alias `/sb`) toggles the status bar and its position.
4. **StatusRule fields** (`ui-tui/src/components/appChrome.tsx`,
   `StatusRule`): left side is priority-reserved — status indicator with
   animated verb + elapsed time while busy, **model name**, **context
   usage (percent / bar)**, session count (clickable); right side yields
   first on narrow terminals — cwd + git branch label, voice label,
   battery readout (color by category), session title, session/turn start
   times. The rule pauses its clock while an overlay covers it.
5. **Overlays** float above everything (they do not replace the screen):
   session switcher, agents overlay, model picker, plugins hub, skills
   hub, billing overlay, approval/clarify/sudo/secret prompts, FPS debug
   overlay. Routed by `ui-tui/src/components/appOverlays.tsx`
   (`FloatingOverlays`, `PromptZone`) and `src/app/overlayStore.ts`.

Density and detail are user controls: `/density` toggles compact rows;
details mode (`/details`) controls how much tool output is shown inline;
themes/skins come from gateway skin data merged over `DEFAULT_THEME`
(`ui-tui/src/theme.ts`): brand name, prompt symbol, welcome/goodbye text,
and colors for banner, accent, border, label, ok/error/warn.

There are **no shipped screenshots** of the TUI in the repo (search found
only app icons). The repo's own visual check is a harness:
`ui-tui/scripts/visual/` — `npm run visual` renders real TUI surfaces
across theme × background scenes to `<tmpdir>/hermes-tui-visual/` as HTML
and screenshots them with Electron (`render.tsx`, `run.mjs`, `shot.mjs`).

## 3. Keybindings

Source: `ui-tui/README.md` "Hotkeys and interactions" and
`ui-tui/src/content/hotkeys.ts` (the in-app `/help` table).

### Main chat input

| Key | Behavior |
| --- | --- |
| `Enter` | Submit draft |
| empty `Enter` twice | Busy + queued messages exist: interrupt current run. Idle + queue: send next queued |
| `Shift+Enter` / `Alt+Enter`, or `\` + `Enter` | Newline / append to multiline buffer |
| `Ctrl+C` | Interrupt active run → clear draft → exit (in that priority) |
| `Ctrl+D` | Exit |
| `Ctrl+L` | New session (same as `/clear`) — note: hotkeys.ts labels Ctrl+L "redraw"; README's table says new session |
| `Ctrl+G` / `Alt+G` (macOS `Cmd+G`) | Open `$EDITOR` with the draft; submit on clean editor exit |
| `Ctrl+V` / `Alt+V` (or `/paste`) | Paste text, else image/path attachment |
| `Tab` | Apply active completion (slash commands via `complete.slash`; paths starting `./ ../ ~/ / @` via `complete.path`) |
| `Up` / `Down` | Cycle completions if open; else edit queued messages; else walk input history |
| `Ctrl+X` | Active session switcher overlay |
| `Ctrl+T` | Expand the live agents roster (keeps draft) |
| `Ctrl+R` / `F7` | Collapse agents |
| `Ctrl+O` | Model picker |
| `Esc Esc` | Discard draft |
| `Ctrl+A`/`Ctrl+E`, `Home`/`End`, `Ctrl+←/→`, `Meta+B/F` | Line start/end, word jumps |
| `Ctrl+W`, `Ctrl+U`, `Ctrl+K`, modified Backspace/Delete, `Ctrl+Z`/`Ctrl+Y` | Delete word, kill to start/end of line, undo/redo |
| `!cmd` | Run a shell command through the gateway, immediately (never queues) |
| `{!cmd}` | Inline shell interpolation into the draft before send |

Rules worth designing around: plain text typed while the agent is busy is
**queued**, not sent; slash commands and `!cmd` execute immediately even
mid-run; the queue auto-drains after each assistant response; `PgUp`/`PgDn`
are deliberately left to the terminal emulator (mouse wheel scrolling is
the TUI's own, with acceleration — `src/lib/wheelAccel.ts`).

### Prompt and picker modes (blocking; main input hotkeys suspend)

- Approval prompt: `Up/Down` + `Enter`, or quick-pick `o`/`s`/`a`/`d`
  (once / session / always / deny); `Esc`/`Ctrl+C` deny.
- Clarify with choices: `Up/Down` + `Enter`, digit quick-pick, `Tab` /
  `Shift+Tab` to switch question, `Enter` on "Other" for free text.
- Sudo / secret: masked input (`ink-text-input`), `Enter` submits,
  `Ctrl+C` cancels with an empty value.
- Resume picker: `Up/Down` + `Enter`, `1-9` quick-pick, `Esc` closes.

### Live agents dock (while subagents run)

`↑/↓` select, `Enter` opens agent details (tools, output, files, usage),
`t` opens a bounded live transcript tail (`g`/`G` top/bottom), `e` opens a
steering form (`Enter` queues guidance for the next tool boundary),
`x` stop child, `X` stop subtree, `Esc` returns to the composer.
(Ctrl+T / Ctrl+R above.)

### Slash commands most relevant to Melange

Client-handled (registry `ui-tui/src/app/slash/`), anything else falls
through to the Python gateway via `slash.exec` / `command.dispatch`:

- Session: `/sessions` (aliases `/switch`, `/session`, `/resume`),
  `/branch` (alias **`/fork`**, RPC `session.branch`), `/model`,
  `/compress`, `/bg`, `/btw`, `/image`, `/usage`, `/personality`,
  `/reasoning`, `/verbose`, `/busy`, `/steer`.
- Ops: `/agents` (alias `/tasks`), **`/replay`**, **`/replay-diff`**,
  `/stop`, `/rollback`, `/browser`, `/skills`, `/plugins`, `/tools`.
- Core: `/help`, `/status`, `/statusbar`, `/queue`, `/details`, `/density`,
  `/copy`, `/paste`, `/save`, `/history`, `/undo`, `/retry`, `/mouse`.

## 4. Sessions in the TUI

- Sessions are first-class and Python-owned: created, resumed, activated,
  closed by `ui-tui/src/app/useSessionLifecycle.ts` against gateway RPCs;
  session metadata arrives as the `session.info` event and drives the
  banner + SessionPanel.
- Switching: `/sessions` opens a **resume picker** overlay fed by a
  `session.list` server request (arrow keys, digits 1–9, Enter). A
  separate **active session switcher** overlay is on `Ctrl+X`
  (`ui-tui/src/components/activeSessionSwitcher.tsx`). The status rule
  shows the live session count.
- **Branching already exists**: `/branch` (alias `/fork`) calls
  `session.branch { session_id, name }` and continues in the branched
  session (`ui-tui/src/app/slash/commands/session.ts`). This is the TUI's
  native idiom for what Melange calls a fork.
- No tabs, no sidebar, no split panes: one session occupies the window;
  other agents' work surfaces through the agents dock and overlays.

## 5. Files and artifacts in the TUI

- **There is no file/artifact panel and no artifact concept.** No preview,
  no file browser, no document list. The desktop app's session-file
  preview webview has no TUI counterpart.
- Files enter a conversation three ways:
  1. **Path completion** in the composer (tokens starting `./`, `../`,
     `~/`, `/`, `@` complete against the filesystem).
  2. **Image attachments**: pasting an image/path (Ctrl+V/Alt+V) inserts a
     collapsed composer token `[[ … ]]` into the draft text. Tokens are
     ordinary editable characters; deleting the token drops the
     attachment; at submit, image tokens expand to nothing in the text
     because the gateway already holds the file in
     `session.attached_images` and splices vision content in at the
     token's position. Pasted text works the same way as a paste token.
     (`ui-tui/src/domain/attachments.ts`)
  3. **Subagent details**: the agents overlay's detail view for a child
     lists its tools, output, **files**, and usage.
- **Replay exists but means something else**: `/replay` replays a
  *completed subagent spawn tree*, not a session timeline. Finished
  fan-outs are kept in an in-memory ring of the last 10
  (`src/app/spawnHistoryStore.ts`); `/replay [N|last|list|load <path>]`
  lists archived trees in a transcript panel (timestamp, count, label,
  path), loads one via the `spawn_tree.load` RPC, and `/replay-diff`
  compares. (`ui-tui/src/app/slash/commands/ops.ts`)
- Tool results can carry an `inline_diff` (payload of the `tool.complete`
  event), rendered with diff coloring in the transcript.
- `/save`, `/copy`, `/paste` cover transcript text; input history persists
  at `~/.hermes/.hermes_history` (or under `HERMES_HOME`).

## 6. What this means for a Melange TUI surface (design hooks)

Concrete extension points found in the code, in order of fit:

1. **Widget apps SDK** (`ui-tui/src/sdk/`): the TUI has a real in-client
   app system. Core integrates through exactly four touch points — input
   dispatch, a viewport-level **modal slot**, **ambient surfaces** (dock
   rows + side rails that reserve real layout space), per
   `ui-tui/src/sdk/host.tsx`. An ambient app declares a zone; the default
   is **`dock-bottom`** — i.e., a persistent bar rendered in the bottom
   zone directly above/below the composer, exactly where GoalBar and the
   LiveAgentsPanel already live. Reference apps: `ui-tui/src/sdk/apps/`
   (weather, ticker). A Melange replay bar (play/step/scrub readout +
   branch name) as an ambient `dock-bottom` widget is the native shape;
   a full timeline inspector fits the modal slot.
2. **Slash namespace is open**: unrecognized commands fall through to the
   Python gateway, and client commands register in
   `ui-tui/src/app/slash/commands/*`. A `/melange` command family would
   sit naturally next to `/replay` and `/branch` — but note `/replay` and
   `/fork` are already taken by spawn-tree replay and session branching,
   so Melange wording should build on those idioms rather than reuse the
   names for different meanings.
3. **Transcript panels**: arbitrary titled panels with sections/rows can
   be pushed into the transcript (`Panel` in `branding.tsx`,
   `ctx.transcript.panel(...)` used by `/replay`) — the idiom for
   showing a record summary, per-poll ops, or a provenance card as text.
4. **Charts exist in-terminal**: `ui-tui/src/lib/charts.ts` renders text
   charts (there is a `charts.test.ts`), enough for a per-frame ops bar
   chart without new rendering tech.
5. **Plain-language precedent**: the UI favors one-line labeled bars
   (GoalBar: `⊙ goal · 3/20 turns · title`), quick-pick keys with letter
   mnemonics in prompts, and status compressed into the StatusRule
   (model · context · cwd/branch). A Melange readout in the same grammar
   would be e.g. `event 25/153 · frame 10/66 · Original` in the status
   rule or dock bar, with words like Play/Pause/Fork spelled out rather
   than icons-only, matching the office-worker readability of the
   desktop bar.
6. The hosted path needs no extra work: anything the Ink client renders
   also appears in the Kindle/browser xterm.js front end unchanged
   (server6.js is a pure terminal proxy).
