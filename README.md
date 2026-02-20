# Gamemaster MCP

Board game rules referee: an **MCP server** plus thin agent that answer natural language questions about rulebooks using **page-cited evidence** from ingested PDFs.

- **CPU-only, local-first**: SQLite FTS5, FAISS, and a small cross-encoder reranker.
- **MCP-centric**: Any MCP client (Cursor, Claude Desktop, etc.) can use the tools.
- **Evidence-first**: Answers are grounded in retrieved chunks with `(source_name, page range)` citations.

## Quick start

### 1. Install

```bash
poetry install
```

Copy `.env.example` to `.env` and set `RULEBOOKS_DIR` to a directory that will contain your rulebook PDFs (e.g. `rulebooks`). PDF paths must be exactly **`rulebooks_dir/<game_id>/<filename>.pdf`** (flat; no subdirectories under `game_id`).

### 2. Ingest a rulebook

Place **text-based** PDFs at `RULEBOOKS_DIR/<game-id>/<filename>.pdf` (scanned/image PDFs are rejected).

Entries use **key=value,key=value** format (keys: `game_id`, `pdf_name`). **Single ingest** = one entry; **batch** = multiple entries. Paths are under **RULEBOOKS_DIR** from env/config.

**Single file:**

```bash
poetry run ingest-rulebook "game_id=wingspan,pdf_name=wingspan_rulebook.pdf"
```

**Multiple files:**

```bash
poetry run ingest-rulebook "game_id=wingspan,pdf_name=wingspan_rulebook.pdf" "game_id=everdell,pdf_name=everdell_rules.pdf" "game_id=ark-nova,pdf_name=ark_nova_rules.pdf"
```

Optional: `--no-faiss` (FTS only). Source display name is always the PDF filename. The MCP server exposes **ingest_pdf** and **ingest_pdfs** (required: game_id, pdf_name; paths use server RULEBOOKS_DIR). **Note:** If you had an existing DB from an older schema, remove `rules_store/` and re-ingest.

### 3. Ask questions (thin agent)

```bash
# Set OPENAI_API_KEY in .env
poetry run ask-agent
```

The agent starts a **session**: it connects to the MCP server over stdio (spawns it as a subprocess), then prompts you for questions. Ask one or more questions; press **Enter with no text** to quit.

- The server preloads the embedder and reranker before accepting connections (**can take 1–2 minutes**). Wait for "Referee ready" on stderr.
- Optional: `--game-id wingspan` and/or `--source-pdf-names all` (or a filename/comma-separated list) to set defaults so the agent doesn’t have to ask.
- Options: `--model`, `--api-key`, `--debug` (writes to `logs/agent_debug_<timestamp>.log`).

**Clarification:** If you omit `--game-id` and the store has multiple games, the agent will ask you to choose (e.g. "Which game would you like to ask about? …"). Reply at the "You:" prompt. Run with `--debug` to inspect prompts and tool calls in the log file.

### 4. Run the MCP server

```bash
poetry run run-mcp
```

The server speaks MCP over **stdio**. Configure your MCP client (e.g. Cursor) to run this command; it will expose:

- **list_games** — list games in the store
- **list_sources** (game_id) — list sources (source_id, source_pdf_name, source_name, page_count) for a game
- **search_rules** (game_id, query, source_pdf_names, k, strategy) — retrieve evidence with citations; source_pdf_names can be "all", a single name, or a priority-ordered list (results include source_priority)
- **get_chunks** (chunk_ids) — fetch full chunk text for answer grounding
- **ask_user_clarification** (message) — ask the user to choose or clarify (e.g. which game, which sources). The server returns a sentinel `{client_action: "prompt_user", message: "..."}`; the client must show the message to the user, get their reply, and **substitute that reply** as the tool result when continuing the conversation (so the model sees the user's reply as the return value).
- **ingest_pdf** (game_id, pdf_name, options?) — path is server RULEBOOKS_DIR/game_id/pdf_name
- **ingest_pdfs** (entries: [{ game_id, pdf_name, options? }], options?) — batch ingest

## Project layout

- `src/gamemaster_mcp/`
  - **mcp_server/** — FastMCP server and tool definitions
  - **ingest/** — PDF extraction, chunking, path validation, run_ingest
  - **index/** — sparse (FTS), dense (FAISS), rerank
  - **storage/** — SQLite schema and store
  - **search/** — retrieval pipeline (search_rules, get_chunks_for_agent)
  - **config.py** — env and settings
- **rules_store/** — SQLite DB and FAISS index (created on first ingest)
- **rulebooks/** — put your PDFs here (or set `RULEBOOKS_DIR`)

## Configuration

See `.env.example`. Main options:

- **RULEBOOKS_DIR** — allowlist root for PDF paths (required for ingest).
- **OPENAI_API_KEY** — for the thin agent.
- **AGENT_DEBUG_LOG_DIR** — where `--debug` logs are written (default: `logs/`, resolved from cwd).

## License

MIT.
