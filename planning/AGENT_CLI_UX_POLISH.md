# Agent CLI UX polish: production-ready ask-agent

Plan for a **clean, polished, visually appealing** CLI experience for **ask-agent**. Goal: as production-ready and pleasant to use as a terminal app can be—clear hierarchy, consistent spacing, subtle emphasis, and predictable behavior. Scope: CLI entrypoint, output, errors, session flow, and progress—not the runner/LLM internals (those are in [POLISH.md](./POLISH.md)).

**Complexity:** S = small, M = medium, L = large.

---

## 0. Visual polish and CLI appeal (emphasis)

Make the session feel intentional and easy to scan. All of this should respect `NO_COLOR` and non-TTY (no color or fancy chars when redirecting or when the user has disabled color).

| Task | Description | Complexity |
|------|-------------|------------|
| **Rulers and separators** | Use a consistent light ruler (e.g. `────────────────` or Unicode box-draw) for section breaks (Agent answer, clarification blocks). Avoid raw `--- Agent ---`; use a line plus a short label so answers and prompts have clear visual boundaries. | S |
| **Spacing and rhythm** | Consistent vertical rhythm: one blank line after the "ready" message, one before "Question:", one after each answer before the next prompt. No cramped or double-spaced blocks. | S |
| **Optional color** | If stderr/stdout is a TTY and `NO_COLOR` is not set: use subtle ANSI (dim for progress, bold or accent for labels like "Referee ready", "Agent", "You"). Fall back to plain text otherwise. Keep colors minimal (e.g. dim + one accent). | S |
| **Progress prefix** | Give progress messages a consistent prefix (e.g. `  › Thinking…`, `  › Calling search_rules…`) so they read as sub-steps and don’t look like stray output. | S |
| **Session bookends** | Clear start: one "Referee ready" line (and optional short rule like "Ask a question; press Enter with no text to quit"). Clear end: on quit, print a short sign-off (e.g. "Goodbye." or "Session ended.") on stderr so the user sees a clean exit. | S |
| **Question prompt** | Use a simple, consistent prompt (e.g. `Question: ` or `  Question: `) so the user always knows where to type. Optionally support a multi-line hint (e.g. "Question (blank to quit): ") without cluttering the prompt. | S |

---

## 1. First-run and startup

| Task | Description | Complexity |
|------|-------------|------------|
| **Clear startup message** | Single line when starting (e.g. `Connecting to rules server…` or `Starting referee…`) and a clear “ready” line when the session is usable (e.g. `Referee ready. Ask a question or press Enter to quit.`). Avoid duplicate or vague “loading models” if the server is what’s slow. | S |
| **Model-load wait** | Document in help/README that the first run can take 1–2 min while the server loads models; optionally show a short “Waiting for server…” with a spinner or elapsed time so the user knows the process is alive. | S |
| **Pre-flight checks** | Before starting the server: if `OPENAI_API_KEY` is missing, exit with a clear message and hint (`Set OPENAI_API_KEY in .env or use --api-key`). Consider optional check that server binary/module is runnable. | S (key check exists; optional: server check) |

---

## 2. Arguments and help

| Task | Description | Complexity |
|------|-------------|------------|
| **Unified help** | Ensure `ask-agent --help` lists all options with consistent formatting. Group args (e.g. “Question”, “Context (game/sources)”, “LLM”, “Session”, “Debug”). Add one-line examples at the bottom (e.g. `Examples: …`). | S |
| **Defaults in help** | Show default values in help where useful (e.g. `--model`, `--game-id` “(optional)”, `OPENAI_API_KEY` from env). | S |
| **Session-only** | CLI is session-only: start agent, prompt for questions, empty line to quit. No single-ask mode. | S (done) |

---

## 3. Output and formatting

| Task | Description | Complexity |
|------|-------------|------------|
| **Stable answer block** | Use a consistent delimiter for the final answer (e.g. `--- Agent ---` / `--- Answer ---` and a blank line after). Ensure citations and “not found” answers are easy to scan. | S |
| **Stderr vs stdout** | All progress and status (Thinking…, Calling X…, Referee ready) on **stderr**; only the "Question:" prompt, user input, and final answer (and clarification prompts) on **stdout** so that redirecting stdout captures only the Q&A. | S |
| **Clarification prompts** | When the agent asks for game or source choice, format “Agent” vs “You” clearly (e.g. `--- Agent ---` / `--- You ---` and `You: ` prompt). Keep input on a single line when possible. | S |
| **No stray debug on stdout** | Audit all `print(..., file=sys.stdout)` or bare `print()`; ensure only intentional user output (answer, clarification prompt) goes to stdout. Progress/debug stay stderr. | S |

---

## 4. Session mode

| Task | Description | Complexity |
|------|-------------|------------|
| **Session prompt** | One clear line for how to quit (e.g. `Ask a question; press Enter with no text to quit.`). Repeat or show a short reminder after each answer if helpful (e.g. next prompt: `Question: `). | S |
| **Empty input** | Treat empty input as quit; Ctrl+C / EOF also quit cleanly with no traceback. | S (partially there; verify EOF/KeyboardInterrupt) |
| **Session context line** | If `--game-id` or `--source-pdf-names` was set, show a single “Context: game=X, sources=Y” at session start so the user knows what’s fixed. | S |

---

## 5. Errors and exit behavior

| Task | Description | Complexity |
|------|-------------|------------|
| **Connection/server errors** | On “Connection closed” or MCP errors, print a short tip on stderr (e.g. “Server may have exited; check stderr for errors.”) and exit with non-zero. Avoid dumping full stack to the user unless --debug. | S (partially there; ensure exit code and no stack unless debug) |
| **LLM/tool errors** | On LLM API or tool-call failure, show a user-friendly one-liner on stderr and exit non-zero. Optionally suggest --debug for details. | S |
| **Exit codes** | Use consistent exit codes (e.g. 0 = success, 1 = validation/usage error, 2 = server/connection error, 3 = LLM/tool error) and document in help or README. | S |

---

## 6. Progress and responsiveness

| Task | Description | Complexity |
|------|-------------|------------|
| **Progress messages** | Keep “Thinking…”, “Calling search_rules…”, etc. on stderr with flush so the user sees activity during long runs. Ensure no progress line is repeated unnecessarily. | S |
| **Timeout message** | If the server doesn’t respond within the tool-call timeout, message should say that the server may still be loading models and suggest waiting or checking the server. | S (message exists in runner; ensure it surfaces in CLI) |

---

## 7. Debug and verbose

| Task | Description | Complexity |
|------|-------------|------------|
| **--debug** | Keep writing full debug log to `AGENT_DEBUG_LOG_DIR`; on startup print exactly one line to stderr with the log path. | S |
| **Optional --verbose** | Consider a --verbose flag that prints tool names and result sizes (or a one-line summary per tool call) to stderr without writing a full debug file. | S |

---

## 8. Optional enhancements (post–minimal polish)

| Task | Description | Complexity |
|------|-------------|------------|
| **Streaming answer** | Stream the final answer tokens to stdout so long answers appear incrementally (see [POLISH.md](./POLISH.md) Agent #5). | M |
| **Config file** | Optional config file (e.g. `~/.config/gamemaster/agent.toml` or project `.gamemaster`) for default model, game_id, or API key path, so users don’t need to pass flags every time. | M |
| **Read question from file** | Optional: support reading first question from stdin or `@file.txt` so scripts can pipe. | S |

---

## Suggested order

1. **Visual polish** (Section 0)—implemented. **Output and streams** (Section 3): stderr vs stdout, answer block, clarification formatting—foundation for everything else.
2. **Errors and exit** (Section 5): consistent exit codes and friendly messages.
3. **Arguments and help** (Section 2): grouped help, examples, defaults.
4. **First-run / startup** (Section 1): one clear “ready” message, optional wait indicator.
5. **Session mode** (Section 4): prompt and context line.
6. **Progress** (Section 6): verify and tighten progress messages.
7. **Debug / verbose** (Section 7): keep --debug; add --verbose if desired.
8. **Optional** (Section 8): streaming, config file, stdin/file input as needed.

Visual polish (Section 0) is emphasized first so the CLI feels intentional and scannable; then output discipline, errors, and help. Several items in Section 0 are already implemented.
