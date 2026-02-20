## Project brief: Board Game Rules Referee (MCP + lightweight agent)

### Goal

Build a sharp, straightforward **MCP server + thin agent** that answers **natural language questions about board game rules** by retrieving evidence from rule PDFs and responding with **page-cited answers**.

The project is intentionally **MCP-centric**: the MCP server encapsulates ingestion, indexing, and retrieval so any agent (OpenAI, Gemini, etc.) can use it. MCP provides standardized **tools/resources** for LLM clients. ([Model Context Protocol][1])

---

## Scope

### In scope

* **Ingest text-based PDFs** (scanned PDFs explicitly out of scope), extract structure, chunk, and store in a local DB.
* **CPU-only, lightweight retrieval**:

  * Sparse search (SQLite FTS5)
  * Dense vector search (FAISS)
  * Reranking (small cross-encoder reranker on CPU)
* **MCP server** that exposes retrieval tools and rulebook “resources” (metadata, sections, sources).
* **Thin agent** that:

  * accepts NL question + game selection
  * asks clarifying questions if needed (edition, expansion, goal board side, etc.)
  * retrieves evidence via MCP
  * answers with **citations** (page ranges, source/version)

### Out of scope

* OCR / scanned PDFs (detect and reject with a helpful message; see text-density rule under ingest)
* Full production hosting and auth (local-first)
* Generating new rules interpretations without evidence (must be evidence-first)

---

## Key user stories

1. “**Do tucked cards count for end-of-round goals?**” → answer with citations and any necessary clarification.
2. “In *Wingspan 1st ed*, what happens at end of round?” → retrieve the exact scoring procedure with page refs.
3. “Does expansion X change rule Y?” → prompt user to select base vs expansion sources, then cite the correct doc.
4. “I can’t find the rule—what’s the closest section?” → return best evidence + confidence/coverage.

---

## System architecture

### A) MCP Server (core)

Implements MCP **tools** (actions) and **resources** (context objects) per MCP spec. ([Model Context Protocol][2])
**Implementation:** **FastMCP** for Python (type hints + docstrings → tool schemas). ([Model Context Protocol][3])
MCP transport: **stdio** (sufficient for CLI-driven agents and for the demo when the backend spawns the MCP server).

**Responsibilities**

* Ingest & index PDFs into:

  * SQLite DB (chunks + metadata + FTS5)
  * vector index (FAISS) + mapping
* Retrieval pipeline: hybrid → rerank → evidence objects
* Provide stable **citations**: `(source_pdf_name, page_start, page_end, chunk_id)` when disambiguating
* Expose tools/resources in an agent-friendly contract

### B) Agent (thin orchestration layer)

LLM client (OpenAI or Gemini, swappable) that:

* chooses MCP tools to call (or follows a fixed plan)
* asks clarifying Qs when ambiguity is detected
* produces final answer strictly grounded in retrieved evidence

Tool calling is supported by both OpenAI and Gemini (different APIs), so you’ll keep an abstraction layer. ([OpenAI Developers][5])

---

## Ingestion Modes

### Mode A — CLI-first ingestion (default)

- Ingestion is run by the user/operator as a one-time setup step whenever adding or updating a game.
- The MCP server owns the ingestion implementation, but it is invoked via a CLI command (e.g., ingest-rulebook) rather than in normal Q&A sessions.
- The Q&A agent does not call ingest tools during question answering.

### Mode B — Agent-assisted ingestion (available as an option “setup wizard”)

- The MCP server exposes ingest_pdf(...) as an MCP tool, enabling an agent to ingest when the user explicitly asks (“add this game / ingest this PDF”).
- The agent may ask for clarifications (which game, optional source name) and then invoke ingestion.
- This mode should be gated behind an explicit server flag (e.g., --enable-ingest-tools) or “admin mode” so ordinary Q&A agents cannot ingest arbitrary local files.

---

## Data model & indexing

### Game

* **game_id** — User-specified unique identifier. Also the folder name under `RULEBOOKS_DIR`: all PDFs for this game live under `rulebooks_dir/<game_id>/`.
* **game_name** — User-specified human-readable name. Defaults to `game_id` if not provided at ingest.

### Source

A source is one PDF. The **full path** is the unique identifier and must be exactly **`rulebooks_dir/<game_id>/<source_pdf_name>.pdf`** (flat; no subdirectories under `game_id`).

* **source_pdf_name** — Name of the PDF file (e.g. `wingspan-rulebook.pdf`, `faq.pdf`). Together with `game_id`, this gives the full path and thus uniquely identifies the source.
* **source_name** — User-specified human-readable label for the source (e.g. "Base rulebook", "FAQ"). Defaults to the PDF file name if not provided.
* **source_id** — App-generated stable ID: **deterministic integer** derived from the full PDF path (e.g. 64-bit hash). Same path → same `source_id`; re-ingest overwrites the existing source record and its chunks. Integer keeps FKs and indexes simple; convert from path hash at ingest time.

No **version** or **source_type** fields; the user names sources according to their own mental model (edition, errata, expansion, etc. can go into `source_name` or the file name).

### Chunking

Chunking is best-effort and robust to varying PDF structure: break on **section boundaries** when detectable (e.g. short lines in all-caps or title-case), otherwise use a **target size** (e.g. ~1200 characters) with **overlap** (e.g. ~180 characters) to avoid mid-sentence splits. Store `section_title` per chunk when a heading was detected. Rulebook PDFs have no universal structure contract; this hybrid approach keeps retrieval useful across different publishers and formats.

### Chunk schema (DB)

Store chunked rule text (not page blobs). Each chunk includes:

* `chunk_id`
* `game_id`, `game_name`
* `source_id`, `source_name`, `source_pdf_name`
* `page_start`, `page_end`
* `text_clean`
* for debug: `pdf_path`, `extract_warnings` (optional)

### Indexes

* **FTS5** on `text_clean`
* **Dense embeddings** (CPU):

  * Embedding model: **intfloat/e5-small-v2** (default; configurable via config/env).
  * Index: FAISS `IndexFlatIP` for small corpora, or HNSW for growth
* **Reranker**:

  * **cross-encoder/ms-marco-MiniLM-L-6-v2** (default; configurable)

---

## Retrieval approach (reasonably cutting-edge, still lightweight)

**Pipeline**

1. **Sparse search** (FTS) top `K1` chunks
2. **Dense search** (vector index) top `K2` chunks
3. Union + dedupe → candidate set
4. **Rerank** candidates with cross-encoder → top `K_final`
5. Return evidence objects: snippet + full text + citations

**Evidence object** (citation does not duplicate chunk_id/game_id; those appear only at top level). When `search_rules` was called with a **priority-ordered list** of `source_pdf_names`, each returned chunk includes **source_priority**: the 0-based index of that chunk’s source in the user’s list (so the agent can surface or use priority when citing).

```json
{
  "chunk_id": 1234,
  "game_id": "wingspan",
  "game_name": "Wingspan",
  "citation": {
    "source_id": 42,
    "source_name": "Wingspan Rulebook",
    "source_pdf_name": "wingspan-rulebook.pdf",
    "page_start": 11,
    "page_end": 11
  },
  "source_priority": 0,
  "question": "do tucked cards count for end of round goals?",
  "score": { "sparse": 0.62, "dense": 0.84, "rerank": 0.91 },
  "snippet": "…",
  "text": "full chunk text…"
}
```
(`source_priority` is present when the search was restricted to a list of sources; omit or null when `source_pdf_names` was `"all"` or a single source.)

---

## MCP server interface

### Tools (minimum viable set)

1. **ingest_pdf(game_id, game_name, pdf_path, source_name=None, options=None) -> IngestReport**

   * **pdf_path** must be exactly `rulebooks_dir/<game_id>/<source_pdf_name>.pdf` (flat; no subdirectories). Path determines `source_pdf_name` from the filename. **source_name** optional; defaults to the PDF file name. **options**: reserved for future use (e.g. chunk size, skip FAISS).
   * Validates text PDF vs scanned: reject if text density is below threshold or zero chunks extracted. Return a clear message for scanned/image PDFs.
2. **list_games() -> [{game_id, game_name}]**

3. **list_sources(game_id) -> [{source_id, source_pdf_name, source_name, page_count, created_at}]**

4. **search_rules(game_id, query, source_pdf_names="all", k=8, strategy="hybrid") -> [EvidenceSummary]**

   * **game_id** required. **source_pdf_names**: `"all"` (default), a single `source_pdf_name`, or a **priority-ordered list** of `source_pdf_name`s. When a list is given: search is **restricted** to those sources only; results are unioned and reranked by relevance (no boost by list order). Each returned evidence item includes **source_priority**: the 0-based index of that chunk’s source in the list, so the agent can use it when presenting or citing.
   * summary = citations + scores + snippet + source_priority (when applicable); no huge payload.

5. **get_chunks(chunk_ids) -> [EvidenceFull]**

   * full = include `text` for final answer grounding. Cap: at most **20 chunks** per call; each chunk’s `text` field at most **4000 characters**.

These map cleanly onto MCP’s “tools” concept. ([Model Context Protocol][2])

### Resources (optional, post-MVP)

Expose read-only context for agents that subscribe to MCP resources (e.g. list of games, sources for a game). Example URIs: `mcp://gamemaster/games`, `mcp://gamemaster/game/{game_id}/sources`. Implement in the Polish milestone if desired.

### Draft Agent tool-usage policy

The agent should treat MCP tools as the only source of truth for rules content and must follow an evidence-first workflow. The agent is intentionally thin: it orchestrates calls to MCP tools, asks minimal clarifying questions, and synthesizes a cited answer.


### Agent principles

* **Evidence-first**: do not answer without citations (or explicitly state “not found”).
* **Clarify ambiguity early**:

  * “Which edition / expansion?”
  * “Which goal board side?” (if relevant)
* **Ask 1 question at a time** (avoid user fatigue)

### Default flow (answering a question)

1. Resolve game context
  - If game_id is not provided or ambiguous: call list_games() and ask the user to select a game.

2. Resolve source context (optional)
  - If the user specified a **game** but **no** source or source list, call list_sources(game_id). If the game has **multiple sources**, ask a clarifying question to resolve **priority order** (e.g. "I see rulebook.pdf and errata.pdf — which should I prefer, or search all with no priority order?"). Then call search_rules with either source_pdf_names="all" or a **priority-ordered list** from the user's answer.
  - If the user already specified a source or list, use it. Otherwise ask one clarifying question at a time when needed.

3. Retrieve evidence

  - Call search_rules(game_id, query, source_pdf_names=..., k, strategy="hybrid"). Use **source_pdf_names** = "all", a single source_pdf_name, or a priority-ordered list when the user or context narrows which sources to search.
  - If results are weak/noisy, the agent may do at most one query refinement pass.

4. Read before answering
  - Call get_chunks(chunk_ids) for the top N results (typically 3–8) and base the answer on the returned full text.

5. Respond with citations
  - Provide a direct answer plus citations using (source_name, page_start–page_end) for each key claim (or source_pdf_name when disambiguating). Use **source_priority** from evidence when the user specified a priority list (e.g. prefer citing higher-priority sources). No version field; users name sources as they like.
  - If evidence conflicts, cite both sources and note the conflict.

### Ingestion flow (adding/updating a game)

- The agent should only call ingest_pdf(...) when the user explicitly requests ingestion (e.g., “add this PDF”, “ingest this rulebook”).

- The agent should collect required metadata (game_id, game_name, pdf_path; optional source_name) and then run ingestion.

- On completion, the agent should summarize the IngestReport (pages, chunks, indexes built, any warnings) and confirm the game appears via list_games() / list_sources().

### Guardrails

- The agent must not hallucinate rule interpretations: if retrieved evidence is insufficient, it must say “not found” and suggest next steps (check edition, ingest FAQ/errata, rephrase query).

- Limit tool calls to keep interactions snappy: typically 1–2 search rounds and ≤ 10 chunks fetched per user question.

- Always prefer returning fewer, higher-quality citations over many low-signal snippets.

---

## LLM provider abstraction (OpenAI + Gemini, swappable)

Implement:

* `LLMClient.generate(messages, tools) -> model_output`
* `LLMClient.parse_tool_calls(model_output) -> calls`
* `LLMClient.finalize(messages + tool_outputs) -> answer`

OpenAI tool calling flow is multi-step (send tools → receive tool call → execute → send tool output). ([OpenAI Developers][5])
Gemini supports function calling similarly, with its own request/response shapes. ([Google AI for Developers][7])

---

## Repository structure (agent-friendly, modular)

```
gamemaster-mcp/
  src/gamemaster_mcp/
    mcp_server/            # FastMCP server + tool definitions
      server.py
      tools_ingest.py
      tools_search.py
      resources.py
    ingest/
      pdf_extract.py       # PyMuPDF extraction + block ordering
      chunking.py
      normalize.py
    index/
      sparse_fts.py
      dense_index.py       # FAISS/HNSW adapter interface
      rerank.py
    storage/
      schema.py
      sqlite_store.py
    agent/
      runner.py            # thin orchestration (OpenAI/Gemini)
      llm_openai.py
      llm_gemini.py
      prompts.py
    config.py              # env + settings
  rulebooks/               # ignored
  rules_store/             # ignored (db + index)
  tests/
  pyproject.toml
  README.md
  .env.example
  .gitignore
```

---

## Security & safety requirements

Even local MCP tools can be chained in unsafe ways; treat tool inputs as untrusted and implement strict path validation, allowlists, and no arbitrary code execution. Recent MCP server vulnerabilities highlight why hardening matters. ([TechRadar][8])

Minimum safeguards:

* PDF path allowlist (within a configured `RULEBOOKS_DIR`)
* Never execute shell commands from tool inputs
* Reject symlinks / path traversal
* Limit returned text per tool call: e.g. get_chunks returns at most 20 chunks, each chunk’s text at most 4000 characters (avoid prompt injection payloads)
* Tool outputs should be structured JSON with tight schemas

### Configuration

Required or common environment variables (see `.env.example`):

* **RULEBOOKS_DIR** — root directory for PDF path allowlist; all ingest paths must resolve under this directory.
* **OPENAI_API_KEY** or **GEMINI_API_KEY** (or equivalent) — for the thin agent’s LLM provider.

---

## Acceptance criteria

* ✅ Ingest a text PDF and produce a DB + vector index with >0 chunks
* ✅ `search_rules` returns relevant evidence with page citations
* ✅ Agent answers with citations and asks clarifying questions when needed
* ✅ Works CPU-only; runs locally; no OCR required
* ✅ OpenAI/Gemini providers are swappable behind a common interface
* ✅ Clear README with “ingest → ask questions” workflow

---

## Delivery milestones (suggested build order)

1. **MVP MCP server (sparse-only)**: ingest → FTS search → citations
2. **Hybrid retrieval**: add dense index adapter
3. **Reranking**: cross-encoder rerank + improved evidence objects
4. **Thin agent**: OpenAI + Gemini provider wrappers + clarification loop
5. **Polish**: resources/TOC, better chunking, hardening
6. **Demo UI** (optional, post-MVP): lightweight UI so non-technical users can ingest rule PDFs and ask questions (see below).

---

## Lightweight Demo UI (post-MVP)

Provide a lightweight, no-CLI demo UI so non-technical users can ingest rule PDFs and ask questions. This is post-MVP: implement after the thin agent and MCP server are stable.

### Core screens
Home / Q&A
- Game selector (dropdown) + optional source filter (all / single / priority-ordered list by source_pdf_name)
- Single chat-style input: “Ask a rules question…”
- Answer rendered with inline citations (source_name + page range)
- Right-side Evidence panel listing top passages (snippet + scores optional) with actions:
- “View passage” (shows full chunk text)
- “Open page” (shows extracted page text or a simple PDF-page preview if available)

Add Game (Ingest Wizard)
- Drag-and-drop PDF upload (text-based PDFs only; detect and reject scanned/image PDFs). PDF must land under rulebooks_dir/game_id/.
- Metadata form: game_id, game_name, optional source_name (defaults to PDF filename)
- Progress + completion summary: #pages, #chunks, capabilities enabled (dense/rerank)

### Implementation guidance

UI can be built as either:
- Streamlit (fastest local demo), or
- Minimal web UI (FastAPI backend + small React/Next.js frontend) for a more product-like feel.

The UI talks to a thin “agent API” (e.g. /ask, /ingest, /list_games). To **fully validate MCP behavior**, the backend should spawn the MCP server as a separate process and communicate via stdio (rather than calling the same Python modules in-process). The UI should never access DB/index files directly.

Nice-to-have
- A collapsible “Debug” panel that shows the MCP tool calls made (search queries, selected chunk IDs, rerank usage) for transparency during demos.
--

If you want one optional stretch goal that pays off fast: add a `warm_cache` tool/CLI that loads embed + rerank models once (so you can flip offline mode for the retrieval stack immediately after).

---

[1]: https://modelcontextprotocol.io/specification/2025-11-25?utm_source=chatgpt.com "Specification"
[2]: https://modelcontextprotocol.io/specification/2025-11-25/server/tools?utm_source=chatgpt.com "Tools"
[3]: https://modelcontextprotocol.io/docs/develop/build-server?utm_source=chatgpt.com "Build an MCP server"
[4]: https://github.com/modelcontextprotocol/python-sdk?utm_source=chatgpt.com "modelcontextprotocol/python-sdk"
[5]: https://developers.openai.com/api/docs/guides/function-calling/?utm_source=chatgpt.com "Function calling | OpenAI API"
[6]: https://modelcontextprotocol.io/specification/2025-06-18/server/resources?utm_source=chatgpt.com "Resources"
[7]: https://ai.google.dev/gemini-api/docs/function-calling?utm_source=chatgpt.com "Function calling with the Gemini API | Google AI for Developers"
[8]: https://www.techradar.com/pro/security/anthropics-official-git-mcp-server-had-some-worrying-security-flaws-this-is-what-happened-next?utm_source=chatgpt.com "Anthropic's official Git MCP server had some worrying security flaws - this is what happened next"
