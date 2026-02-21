# Gamemaster MCP

## Overview

Gamemaster is a **board game rules referee**: an MCP server plus an optional thin chat client (CLI) that answers natural-language questions using **page-cited evidence** from ingested rulebook PDFs. Retrieval is light (CPU-only and fully local): SQLite FTS5, FAISS, and a small cross-encoder reranker. Any MCP client (Cursor, Claude Desktop, etc.) can use the server; the included CLI is a working example client.

### Demo
<img src="docs/images/gamemaster_demo.gif" alt="Gamemaster demo" width="500" />

## Features

- **Evidence-first answers**: Answers are grounded in retrieved chunks with `(source_name, pp. start–end)` citations.
- **Hybrid context retrieval**: Sparse (FTS5) + dense (FAISS) merged with RRF plus a cross-encoder reranker, for evidence retrieval.
- **Seamless MCP Integration**: Tools and resources exposed over MCP (stdio); use the server from any MCP client.
- **Built-in ingestion**: Ingest tools are part of the server; the agent can add rulebooks for you.

## Tools

The MCP server exposes:

- `list_games` - list games in the rules store
- `list_sources` - list sources (PDFs) for a game in the rules store
- `search_rules` - retrieve evidence chunks with citations from the rules store
- `get_chunks` - fetch full chunk text for evidence
- `ask_user_clarification` - wrapper for request-for-clarification message, so agent and client can share a strict protocol for "ask user and pass reply back as tool result"
- `ingest_pdf` - ingest one rulebook PDF to the rules store
- `ingest_pdfs` - batch ingest multiple PDFs

## Installation

1. Clone the repo and install with Poetry:

   ```bash
   poetry install
   ```

2. Copy `.env.example` to `.env` and set at least:
   - **RULEBOOKS_DIR** — directory for your rulebook PDFs (e.g. `rulebooks`).
   - **OPENAI_API_KEY** — required for the included `ask-gamemaster` MCP client CLI.

## Configuration

All settings are via environment variables (or a `.env` file in the project root). See `.env.example` for a full list.

| Variable | Default | Description |
|---------|---------|-------------|
| RULEBOOKS_DIR | `rulebooks` | Root for PDF paths; ingest uses `<RULEBOOKS_DIR>/<game_id>/<pdf_name>`. |
| RULES_STORE_DIR | `rules_store` | Directory for SQLite DB and FAISS index. |
| OPENAI_API_KEY | - | Required for `ask-gamemaster`. |
| OPENAI_MODEL | `gpt-5-mini` | Model used by the `ask-gamemaster` CLI. |
| EMBED_MODEL | `intfloat/e5-small-v2` | Sentence embedding model. |
| RERANK_MODEL | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Reranker for search. |
| TEXT_DENSITY_MIN_CHARS_PER_PAGE | `100` | Min chars/page to accept a PDF (rejects scanned/image PDFs). |
| AGENT_DEBUG_LOG_DIR | `logs` | Where `--debug` agent logs are written. |

Optional: `GET_CHUNKS_MAX_CHUNKS`, `GET_CHUNKS_MAX_CHARS`, `SEARCH_K_SPARSE`, `SEARCH_K_DENSE`, `HF_HOME`, `TRANSFORMERS_CACHE`, `HF_HUB_CACHE`.

## Usage

### Manually ingest rulebooks

Optional - the agent can also do this for you from the chat CLI.

Place **text-based** PDFs at `RULEBOOKS_DIR/<game_id>/<filename>.pdf`. Scanned/image PDFs are rejected.

**Single file:**

```bash
poetry run ingest-rulebook "game_id=wingspan,pdf_name=wingspan_rulebook.pdf"
```

**Multiple files:**

```bash
poetry run ingest-rulebook "game_id=wingspan,pdf_name=wingspan_rulebook.pdf" "game_id=everdell,pdf_name=everdell_rules.pdf"
```

### Chat via MCP client CLI

```bash
poetry run ask-gamemaster
```

The CLI starts the MCP server as a subprocess and runs the agent so you can chat with it. Press **Enter with no text** to quit. First run can take 1–2 minutes while models load; wait for "Gamemaster ready".

- **Optional:** `--game-id <id>` and/or `--source-pdf-names all` (or a comma-separated list) to skip clarifying questions from the agent.
- **Debug:** `--debug` writes prompts and tool calls to `AGENT_DEBUG_LOG_DIR` for the CLI session.

### Run the MCP server only

```bash
poetry run run-mcp
```

The server speaks MCP over **stdio**. Point any MCP client at this command to use the tools; the included `ask-gamemaster` CLI is a working example client.

---

### Project layout

```
gamemaster-mcp/
├── src/gamemaster_mcp/
│   ├── mcp_server/    # FastMCP server, tools, resources, instructions
│   ├── ingest/        # PDF extraction, chunking, path validation, run_ingest
│   ├── index/         # Sparse (FTS), dense (FAISS), rerank
│   ├── storage/       # SQLite schema and store
│   ├── search/        # Retrieval pipeline (search_rules, get_chunks_for_agent)
│   ├── agent/         # LLM client, MCP session, runner (ask-gamemaster)
│   ├── cli/           # ingest-rulebook and ask-gamemaster CLIs
│   └── config.py      # Env and settings
├── rules_store/       # SQLite DB + FAISS index (created on first ingest)
├── rulebooks/         # PDFs go here (or set RULEBOOKS_DIR)
├── .env               # Copy from .env.example
└── pyproject.toml
```

## Future Work

- [Long-lived chat sessions in client](docs/LONG_LIVED_SESSION.md)