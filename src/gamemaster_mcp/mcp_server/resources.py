"""MCP resources: ingest instructions, game/source clarification templates, question-answering procedure."""

from __future__ import annotations

from gamemaster_mcp.config import RULEBOOKS_DIR


def get_question_answering_instructions() -> str:
    """Core procedure for answering rulebook questions (evidence, workflow, guardrails)."""
    return """**Workflow for answering rulebook questions (exact steps to follow):**
1. **Resolve Game Context:** If game_id is missing or ambiguous → read resource **clarification/game** for the exact steps to take. ALWAYS resolve game_id if the user did not explicitly specify, even if there is only a single game in the database. Do not ask extraneous questions. Do not move on until you have full clarity on the game_id.
2. **Resolve Sources Context:** If the user did not specify which source to search → read resource **clarification/source** for the exact steps to take. Do not ask extraneous questions. Do not move on until you have full clarity on the sources.
3. **Retrieve Evidence:** Call **search_rules(game_id, query, source_pdf_names=..., k=8, strategy="hybrid_rerank")**. Use the returned chunk_ids and each result's citation (source_name, page_start, page_end) as evidence candidates.
4. **Read Evidence:** Call **get_chunks(chunk_ids)** for the top 3-8 chunk_ids from search. Use each chunk's text and its citation fields (source_name, page_start, page_end) as evidence for your answer.
5. **Answer With Citations:** Provide direct answer plus citations. Cite each claim as (source_name, pp. page_start-page_end). Use source_priority from search results when the user gave a source order (prefer citing higher-priority sources first).

**Guardrails for answering rulebook questions:**
- Limit tool calls: typically 1-3 search rounds, ≤ 10 chunks fetched per question.
- Prefer fewer, higher-quality citations over many low-signal snippets.
- Do not hallucinate rule interpretations. If not found in the store, say so; do not offer uncited answers.

**Core principles for answering rulebook questions:**
- **Evidence-first**: Your interpretations must be based on concrete evidence. Never answer without citations from the rules store (what list_sources and search_rules return). If you're unable to find sufficient evidence, do **not** offer to give an uncited, "unofficial", or "common-play" interpretation. Instead, suggest that the user rephrase the query or ingest more PDFs (via ingest_pdf or ingest_pdfs). For how/where to add PDFs, read resource **ingest_instructions**.
- **Citations**: Always cite for each key claim.
- **Conflicts**: If evidence from different sources conflicts, cite both and note the conflict.
"""


def get_ingest_instructions() -> str:
    """Instructions for adding and ingesting PDF rulebooks."""
    root = RULEBOOKS_DIR.resolve()
    return f"""# Ingesting rulebooks

**Place file(s) first:** The user must place each PDF under <rulebooks_dir>/<game_id>/<pdf_name> **before** asking you to ingest. Tell them to put the file(s) there, then say when ready so you can run the ingest.

**Where to put PDFs:** One folder per game:

- **Rulebooks directory:** `{root}`
- **Path rule:** `<rulebooks_dir>/<game_id>/<filename>.pdf`
- **Example:** For game_id `wingspan`, put files in `{root}/wingspan/`, e.g. `{root}/wingspan/rulebook.pdf`.

**Required for each file:** `game_id`, `pdf_name` (filename only). Full path is `<rulebooks_dir>/<game_id>/<pdf_name>`.

**When the user wants to add rulebook(s):** 
1. **Single file:** If they want to add **one** PDF, call **ingest_pdf(game_id, pdf_name)**. **Multiple files:** If they want to add **more than one** PDF (for the same game or for multiple games), call **ingest_pdfs(entries)** with a list of entries (each with game_id, pdf_name).
2. If they have not specified game_id and/or pdf_name (or the full list for multiple), call **ask_user_clarification**(message=...) with a message that reminds them the file(s) must already be at <rulebooks_dir>/<game_id>/<pdf_name>, then asks for the missing info. For single: e.g. "Which game is this for (game_id)? What is the exact PDF filename (pdf_name)?" For multiple: "Which games and filenames? Give me game_id and pdf_name for each." Use the tool reply as game_id and pdf_name, or parse it into a list of entries for **ingest_pdfs**. Do not move on until you have full clarity on the required parameters for the appropriate tool call.
3. Call the appropriate tool (**ingest_pdf** or **ingest_pdfs**) and report success or the tool error(s) (e.g. file not found, low text density).

**Tools:** `ingest_pdf` for a single file; `ingest_pdfs` for multiple.
"""


def get_clarification_game() -> str:
    """Template for asking the user which game they mean."""
    return """# Game clarification

When the user has not specified which game they're asking about (or intent is ambiguous), ask them to choose one.

1. Call **list_games()** to get the current games in the store.
2. Call **ask_user_clarification(message=...)** with a message that includes the game list and asks them to pick. Always ask, even if there is only one game in the list. Ask this exact question:

   "I have these games in the store: [paste the list from list_games]. Which game do you want to ask about? Please choose one (by game_id or name)."

3. Use the tool reply as the game_id (or match to game_id) for the next step.
"""


def get_clarification_source() -> str:
    """Template for asking the user which source(s) to search when a game has multiple PDFs."""
    return """# Source clarification

When the game has multiple ingested sources (PDFs) and the user has **not** specified which source to use, ask them to specify.

1. Call **list_sources(game_id)** to get the source names (PDF names) for that game.
2. Call **ask_user_clarification(message=...)** with a message that lists those sources and asks for choice. Ask this exact question:

   "I see sources: [paste the source names from list_sources]. Please specify the set of sources to search from, in priority order, or say 'all' to search every source with no priority order."

3. Use the tool reply as **source_pdf_names** in search_rules: either the user's ordered list of source names or the string "all".
"""