"""MCP resources: ingest instructions, game/source clarification templates."""

from __future__ import annotations

from gamemaster_mcp.config import RULEBOOKS_DIR


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

**When the user wants to add rulebook(s):** If they want to add **one** rulebook, call **ingest_pdf**(game_id, pdf_name) once the file is in place. If they want to add **several**, call **ingest_pdfs** with a list of entries (each with game_id, pdf_name). If they haven't specified game_id/pdf_name (or the full list for multiple), call **ask_user_clarification**(message=...) to ask for the missing info; use the tool reply as game_id and pdf_name, or parse it into a list for ingest_pdfs.

**Tools:** `ingest_pdf` for a single file; `ingest_pdfs` for multiple.
"""


def get_clarification_game() -> str:
    """Template for asking the user which game they mean."""
    return """# Game clarification

When the user has not specified which game they're asking about (or intent is ambiguous), ask them to choose one.

1. Call **list_games()** to get the current games in the store.
2. Call **ask_user_clarification** with a message that includes that list and asks them to pick. Ask this exact question:

   "I have these games in the store: [paste the list from list_games]. Which game do you want to ask about? Please choose one (by game_id or name)."

3. Use the reply as the game_id (or match to game_id) for the next step.
"""


def get_clarification_source() -> str:
    """Template for asking the user which source(s) to search when a game has multiple PDFs."""
    return """# Source clarification

When the game has multiple ingested sources (PDFs) and the user has **not** specified which to search, ask them to specify.

1. Call **list_sources(game_id)** to get the source names (PDF names) for that game.
2. Call **ask_user_clarification** with a message that lists those sources and asks for choice. Ask this exact question:

   "I see sources: [paste the source names from list_sources]. Please specify the set of sources to search from, in priority order, or say 'all' to search every source with no priority order."

3. Use the returned reply as **source_pdf_names** in search_rules: either the user's ordered list of source names or the string "all".
"""
