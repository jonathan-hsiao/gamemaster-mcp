# Add Ingest to Agent UX (Option A)

**Goal:** Let users trigger ingest from the agent CLI in a seamless way, with no new CLI code—rely on the agent and existing MCP tools.

**Principle:** The MCP server already exposes `ingest_pdf` and `ingest_pdfs`. The agent already receives those tools. We only need instructions and resources so the model knows when and how to use them.

**Explicit requirement:** The agent must support both **single ingest** and **multiple ingest** depending on the user’s chat. If the user asks to add one rulebook, use **ingest_pdf**. If the user asks to add several (e.g. “ingest these three rulebooks” or lists multiple game_id/pdf_name pairs), use **ingest_pdfs**. Same seamless UX and minimal complexity—no new CLI surface, just clear instructions so the model picks the right tool.

---

## Current state

- **ingest_pdf** / **ingest_pdfs** are exposed by the MCP server and listed in the agent’s tool set.
- Server instructions mention: “suggest that the user rephrase the query or ingest more PDFs (via ingest_pdf or ingest_pdfs). For how/where to add PDFs, read resource **ingest_instructions**.”
- Resource **ingest_instructions** (from `get_ingest_instructions()`) describes RULEBOOKS_DIR, path rule, and that the agent should use `ingest_pdf` / `ingest_pdfs`.

What’s missing is a clear **workflow for “user wants to add a rulebook”**: when to call ingest, what to ask the user, and how to phrase the “put the file here first” guidance.

---

## Option A: Instruction and resource tweaks only

### 1. Add an ingest workflow step (instructions)

In **SERVER_INSTRUCTIONS** (e.g. in `instructions.py`), add a short “When the user wants to ingest” block, for example:

- **When the user asks to add, ingest, or upload rulebook(s):**
  1. **Single file:** If they name one game and one PDF, use **ingest_pdf(game_id, pdf_name)**. **Multiple files:** If they name several rulebooks (or list multiple game_id/pdf_name pairs), use **ingest_pdfs** with a list of `{ game_id, pdf_name }` entries. Choose the tool to match what the user asked for.
  2. If they have not specified `game_id` and/or `pdf_name` (or the full list for multiple), ask for the missing info: e.g. “Which game is this for (game_id)? What is the exact PDF filename (pdf_name)?” or for multiple, “Which games and filenames? Give me game_id and pdf_name for each.”
  3. Remind them: “The file(s) must already be at `RULEBOOKS_DIR/<game_id>/<pdf_name>`. Place them there, then tell me and I’ll run the ingest.” (Optionally: “Read resource **ingest_instructions** for the exact path.”)
  4. Call the appropriate tool and report success or the tool error(s) (e.g. file not found, low text density).

Keep this block next to the existing “Evidence-first” and “Workflow” sections so the model sees it in the same place as other workflows.

### 2. Strengthen ingest_instructions resource

In **get_ingest_instructions()** (resources.py), ensure the text:

- States that **the user must place the PDF under RULEBOOKS_DIR/game_id/pdf_name before** asking the agent to ingest.
- Says explicitly: “If the user wants to add one rulebook, call **ingest_pdf**(game_id, pdf_name) once the file is in place; if they want to add several, call **ingest_pdfs** with a list of entries. If they haven’t specified game_id/pdf_name (or the full list), ask for the missing info.”

No new APIs or tools—only clearer wording so the model and the user both know the sequence: place file(s) → tell agent → agent calls ingest_pdf or ingest_pdfs as appropriate.

### 3. Optional: “ingest” in the list of things the agent can do

In the same SERVER_INSTRUCTIONS, in the intro or “Core principles” area, add one line such as:

- “You can also **ingest** new rulebooks: when the user wants to add a PDF, guide them to put it in RULEBOOKS_DIR/game_id/filename, then call ingest_pdf (or ingest_pdfs) and report the result.”

This makes “ingest” a first-class capability in the agent’s self-model without adding code.

---

## User experience (after changes)

- User runs `ask-agent` (no new command).
- **Single ingest:** User says e.g. “I added wingspan_rulebook.pdf for wingspan, please ingest it” or “I want to add the Wingspan rulebook.” Agent asks for game_id/pdf_name if missing, reminds where to put the file, then calls **ingest_pdf** and reports success/failure.
- **Multiple ingest:** User says e.g. “I added rulebooks for wingspan and everdell, ingest them” or lists several game_id/pdf_name pairs. Agent gathers the list (asking for any missing entries), reminds about RULEBOOKS_DIR placement, then calls **ingest_pdfs** with the list and reports result(s).
- Same session continues for follow-up questions or more ingests; no switching to another CLI.

---

## Out of scope for Option A

- No new CLI commands or subcommands.
- No parsing of “ingest …” in the agent CLI (that would be Option B).
- No change to MCP tool schemas or server behavior—only prompts and the ingest_instructions resource.

---

## Summary

| What | Where |
|------|--------|
| “When user wants to ingest” workflow: choose **ingest_pdf** (single) or **ingest_pdfs** (multiple) from user’s chat; ask for missing game_id/pdf_name or list; remind about path; call tool; report result | `SERVER_INSTRUCTIONS` in `instructions.py` |
| Clear “place file first, then tell me” and “call ingest_pdf when you have game_id and pdf_name” | `get_ingest_instructions()` in `resources.py` |
| Optional one-liner that the agent can ingest rulebooks | Intro / principles in `instructions.py` |

All changes are in **planning** (this doc) and in **instruction/resource text** only; no new code paths or CLI surface.
