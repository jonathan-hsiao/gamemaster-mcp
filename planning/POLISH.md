# Polish plan: MCP and Agent to ~90% production-ready

Tasks in each section are ordered by **impact**. Each task includes a **complexity** estimate (S / M / L) and a short **rationale**.

**Complexity legend:** S = small (hours), M = medium (half day–1 day), L = large (multiple days or non-trivial design).

---

## Database & retrieval

### Is the current setup close to modern best practice? What’s missing?

**What you have (strong base):**
- **Storage:** SQLite + WAL, normalized schema (games → sources → chunks), FTS5 with triggers. Good for local/single-writer.
- **Chunking:** Section-aware (headings), ~1200 chars + 180 overlap fallback. Aligns with “respect structure, then size.”
- **Sparse:** FTS5 BM25, NL query → tokenized OR terms (2+ char, 4+ char prefix). Solid for keyword/literal match.
- **Dense:** FAISS (exact search, IndexFlatIP), E5-style query/passage prefix. Correct for bi-encoder retrieval.
- **Pipeline:** Sparse + dense candidates → merge → optional cross-encoder rerank. Matches common “hybrid + rerank” pattern.
- **Metadata:** game_id and source_pdf_names filtering; source_priority for user-ordered sources.

**Gaps vs current best practice:**

| Area | Current | Best practice / what’s missing |
|------|--------|--------------------------------|
| **Hybrid merge** | Sort by `(dense_score, -bm25_score)` — different scales, dense dominates. | **RRF (reciprocal rank fusion):** combine rank positions, e.g. `score = 1/(k+rank_sparse) + 1/(k+rank_dense)`. Same pattern as ColBERT/LangChain etc. |
| **Model loading** | Embedder and reranker loaded per request in `dense_search()` and `rerank()`. | **Cache/singleton:** load once per process (or lazy once); avoids repeated load and speeds up repeated queries. |
| **Index lifecycle** | FAISS index read from disk on every dense search. | For a long-running server: **keep index in memory** (or warm cache); optional incremental updates instead of full reload. |
| **Chunking** | Section + size/overlap is good. | Optional: **section_title** (or other metadata) in retrieval filters; or semantic/sentence-level chunking for very short sections. Not critical for rulebooks. |
| **Query handling** | NL → tokenized OR terms. | Optional: **query expansion** or **synonyms** for game-specific terms; stopwords for “the”, “how”, “when” if they hurt precision. |
| **Observability** | No logging inside pipeline. | **Log** strategy, k, candidate counts, rerank top-k, latency per stage (sparse / dense / rerank) for tuning and debugging. |

So you’re roughly **75–80%** of the way to “modern best practice” for a local RAG stack. The highest-impact improvements are **RRF for hybrid merge** and **caching embedder/reranker** (and optionally keeping the FAISS index in memory if you run a server).

---

### For this use case, is retrieval better than putting the whole rulebook in context?

**Short answer:** Yes. Retrieval is the better default for your product (citation quality, multi-doc, cost, and scale). Putting the full rulebook in context is only a reasonable shortcut for a single short PDF when you accept weaker citations.

**Why retrieval fits this use case:**

1. **Citations:** You need `(source_name, page_start–page_end)`. With retrieval, chunks already have page bounds; the model is grounded on those passages. With the full doc in context, the model can still cite but you have no structured tie to specific spans, so citations are more likely to be vague or wrong.
2. **Multiple sources:** You support multiple PDFs per game (rulebook, errata, FAQ) and user-chosen priority. That doesn’t fit “dump everything in context” once you have more than one or two docs.
3. **Size and cost:** A 30-page rulebook can be ~15k–25k words (~100k+ chars). Fitting that in context every turn is expensive and slow; retrieval keeps the prompt small (e.g. 8 chunks × ~1.2k chars).
4. **Focus:** Retrieval forces the model to use the most relevant parts; a full rulebook in context encourages skimming and can dilute important bits.

**When “full rulebook in context” is acceptable:**

- Single, short rulebook (e.g. &lt;20 pages, &lt;10k words) and you’re okay with simpler setup and less strict citation guarantees. You still lose explicit (page_start, page_end) and multi-source priority; fine for a throwaway or demo, not for your current “evidence-first, page-cited” product.

**Recommendation:** Keep retrieval as the core. If you ever add a “simple mode” for one short PDF, you could offer “ingest optional: just paste or upload the text and we’ll put it in context” as a separate path, but the main flow should stay retrieval-based.

---

### Retrieval polish tasks (by impact, with complexity)

1. **Use RRF for hybrid merge** — Replace (dense_score, bm25_score) sort with reciprocal rank fusion so sparse and dense rankings are combined by rank, not raw scores.  
   **Complexity:** S  
   **Rationale:** Small change in pipeline; well-documented formula; big quality gain for hybrid.

2. **Cache embedder and reranker** — Load once per process (or lazy singleton); reuse in `dense_search` and `rerank`.  
   **Complexity:** S  
   **Rationale:** Few lines; avoids repeated model load and speeds up every query after the first.

3. **Keep FAISS index in memory (server scenario)** — If run as a long-lived server, load the index once and reuse; optional incremental add/remove for ingest.  
   **Complexity:** M  
   **Rationale:** Depends on process model (CLI vs server); shared state and invalidation on re-ingest need a clear design.

4. **Pipeline observability** — Log strategy, k, candidate counts, rerank top-k, and latency per stage (sparse / dense / rerank).  
   **Complexity:** S  
   **Rationale:** Add logging in pipeline; no new deps; helps tuning and debugging.

5. **Optional: query normalization** — Light cleanup (e.g. strip, collapse spaces) or stopword removal for very common words if BM25 precision suffers.  
   **Complexity:** S  
   **Rationale:** Optional; only if you see noisy sparse results.

---

## Ingestion

### How close to modern best practice? What’s missing?

**What you have (strong base):**
- **Path validation:** Allowlist under `RULEBOOKS_DIR`, exact `rulebooks_dir/<game_id>/<filename>.pdf`, no symlinks, path traversal rejected, `.pdf` and is-file checks. Clear `PathRejectedError`.
- **PDF extraction:** PyMuPDF (fitz), blocks per page, **2-column ordering** (median-x split, then y then x). **Heading detection** (length, all-caps, title-case) for section boundaries.
- **Chunking:** Section-aware with size/overlap fallback (~1200 chars, 180 overlap); **normalize** (whitespace, line breaks) and **fix_hyphenation** (end-of-line hyphens). Page bounds and optional `section_title` per chunk.
- **Re-ingest semantics:** Deterministic `source_id` from path; re-ingest = delete chunks by source, insert new chunks, then update FAISS (remove old ids, add new). Same path = same source; no duplicate sources.
- **Guards:** Text density (min chars/page) to reject scanned/image PDFs; “no chunks” rejected with clear error.
- **Report:** Returns `page_count`, `chunk_count`, `index_built`, `warnings` (list exists, though currently unused).

**Gaps vs current best practice:**

| Area | Current | Best practice / what’s missing |
|------|--------|--------------------------------|
| **DB vs index consistency** | DB commit then FAISS update. If FAISS fails after DB commit, index is out of sync with DB (stale or missing ids). | **Atomic index update:** write FAISS to a temp file, then rename into place so the live index is never half-updated; or document “rebuild index from DB” and provide a small script. |
| **Concurrency** | No lock. Two ingests (even different sources) can interleave DB + FAISS writes and corrupt the index. | **Single-writer:** document “run one ingest at a time” or add a process/file lock around the full ingest (path → DB → index). |
| **Observability** | No logging in `run_ingest` or chunking (path, page count, chunk count, duration, errors). | **Log** at INFO: path, game_id, page_count, chunk_count, index_built, duration; on error log and re-raise. |
| **Warnings** | `warnings` list is never populated. | **Populate warnings:** e.g. “very few chunks”, “very long section”, “no headings detected (size-only chunking)”; return in report. |
| **Input validation** | Path and density checked. No explicit caps. | **Optional caps:** max pages or max total chars per ingest to avoid accidental 1000-page runs; validate `game_id` / `source_name` non-empty and length. |
| **Configurable chunking** | `MAX_CHARS` and `OVERLAP_CHARS` are constants. | **Config:** env or options for max_chars / overlap (and optionally min_chunk_chars) so you can tune without code change. |
| **PDF edge cases** | PyMuPDF throws on password-protected or badly corrupted PDFs. | **Catch** and return a structured error (“PDF is password-protected or unreadable”) instead of raw exception. |

So you’re roughly **70–75%** of the way to “modern best practice” for ingest. The highest-impact improvements are **atomic index write** (or clear recovery path), **single-writer guarantee or lock**, and **observability + warnings**.

---

### Ingestion polish tasks (by impact, with complexity)

1. **Atomic FAISS index update** — Write the new index to a temp file (e.g. `index.faiss.tmp`), then rename over the live path so the in-use index is never half-written. On failure, leave the previous index in place.  
   **Complexity:** S  
   **Rationale:** Small change in `run_ingest`; avoids corrupted index if save fails or process is killed.

2. **Observability: ingest logging** — Log at INFO: path, game_id, page_count, chunk_count, index_built, duration; on exception log and re-raise so failures are visible.  
   **Complexity:** S  
   **Rationale:** Stdlib logging; a few lines at start/end and in except; no new deps.

3. **Single-writer / lock** — Document that only one ingest should run at a time, or add a file lock (e.g. `rules_store/ingest.lock`) held for the duration of `run_ingest` so concurrent ingests don’t corrupt the index.  
   **Complexity:** S  
   **Rationale:** Either doc-only or a small lock file; prevents the main production bug (concurrent ingest).

4. **Populate warnings** — In `run_ingest`, add warnings when appropriate (e.g. chunk_count &lt; 3, no section_title in any chunk, chars_per_page just above threshold). Return them in the report so callers can show “ingested with warnings.”  
   **Complexity:** S  
   **Rationale:** You already return `warnings`; just fill it in a few cases.

5. **Optional: configurable chunking** — Read `MAX_CHARS` / `OVERLAP_CHARS` from config or `options` (env or ingest params) so you can tune without code change.  
   **Complexity:** S  
   **Rationale:** One or two config knobs; default to current constants.

6. **Optional: input caps and PDF errors** — Reject or cap when page_count or total_chars exceed a limit; catch PyMuPDF errors and return a clear message (e.g. “PDF is password-protected or corrupted”).  
   **Complexity:** S  
   **Rationale:** Prevents runaway ingests and friendlier errors for users.

---

## MCP

### 1. Single source of truth for tool schemas

**Impact:** High. Eliminates drift between MCP (docstrings/signatures) and the agent’s `tool_schemas.py`; MCP truly “instructs” any client, including the thin agent.

**Tasks:**
- Expose a way to get OpenAI-style tool schemas from the MCP server (e.g. FastMCP introspection, or a small module that both MCP and agent import from).
- Thin agent: load or derive tool schemas from that single source instead of hand-maintaining `tool_schemas.py` for search/ingest. Keep `ask_user_clarification` as an agent-only schema (not an MCP tool).

**Complexity:** M  
**Rationale:** Requires deciding where the canonical schema lives (FastMCP vs shared Python schema module) and wiring the agent to it; no new infra.

---

### 2. Input validation and structured errors in tools

**Impact:** High. Prevents bad inputs from reaching storage/search; clients and the agent get consistent, parseable errors.

**Tasks:**
- Validate in MCP tool layer: `game_id` (format/length), `k` (range), `strategy` (enum), `source_pdf_names` (shape), `chunk_ids` (length/cap), ingest `pdf_path` (path rules already exist; ensure they’re used at tool boundary).
- Define a small error shape (e.g. `{ "error": true, "code": "invalid_game_id", "message": "..." }`) and return it instead of raising for bad input; reserve exceptions for real failures.
- Agent: when a tool returns an error object, pass it through (or summarize) so the model can react (e.g. “Invalid game_id; try list_games.”).

**Complexity:** M  
**Rationale:** Straightforward validation code and one shared error format; touch each tool and possibly the agent’s tool-result handling.

---

### 3. Observability: tool invocation logging

**Impact:** High for production debugging and auditing.

**Tasks:**
- Log each tool call at INFO: name, sanitized args (no secrets), duration, success or error code.
- Optionally add a request/correlation id (e.g. from MCP context if available) so agent runs can be tied to tool calls later.

**Complexity:** S–M  
**Rationale:** Add a small logging layer around tool dispatch or inside each tool; no new dependencies if using stdlib `logging`.

---

### 4. MCP resources (optional but valuable)

**Impact:** Medium. Lets clients (and future agent flows) pull static context on demand instead of hard-coding it in prompts.

**Tasks:**
- Expose one or more resources (e.g. “rules store schema” or “how to cite”) if that would reduce prompt size or keep docs up to date.
- Document resource URIs in server `instructions` or README so clients know what’s available.

**Complexity:** S  
**Rationale:** FastMCP supports resources; add a few URIs and handlers; low effort if content already exists.

---

### 5. Security hardening (if moving beyond local/single-tenant)

**Impact:** High in multi-tenant or untrusted environments; lower for local-only.

**Tasks:**
- Add transport-level auth if the server is ever exposed (e.g. MCP auth where supported).
- Consider rate limits per client/session for expensive tools (e.g. `search_rules`, `ingest_pdf`).
- Ensure path validation and DB access stay strict; no arbitrary file or DB access from tool args.

**Complexity:** M–L  
**Rationale:** Auth and rate limiting depend on deployment (stdio vs HTTP, single vs multi user); path/DB checks are mostly already there.

---

## Agent

### 1. Use single source of truth for tool schemas (from MCP)

**Impact:** High. Same goal as MCP #1: agent gets “what tools exist and what they do” from MCP (or shared module), not from a duplicate file.

**Tasks:**
- After MCP-side schema source exists, change the agent to load/derive LLM tool schemas from it.
- Keep `ask_user_clarification` (and any other agent-only tools) as additive schemas only the agent sees.

**Complexity:** M  
**Rationale:** Depends on MCP schema work; then it’s wiring and tests so the agent still gets the right tools + descriptions.

---

### 2. Observability: always-on logging and optional tracing

**Impact:** High for production: debug failures, tune prompts, monitor cost and latency.

**Tasks:**
- Always-on structured logging for each run: input (question, game_id, flags), turn count, tool calls per turn, final answer length, errors. Redact or hash PII if any.
- Optional: trace_id or run_id that flows into MCP tool logs so one run is one trace.
- Keep `--debug` for full prompt/message dumps; consider a “verbose” level that logs tool names and result sizes without full bodies.

**Complexity:** M  
**Rationale:** Add a logger and a few log lines in the runner and CLI; optional tracing is a bit more if you add OpenTelemetry or similar.

---

### 3. Retries for LLM and tool calls

**Impact:** High for reliability; reduces spurious failures from transient API or I/O errors.

**Tasks:**
- LLM: retry with backoff (e.g. 1–2 retries, exponential backoff) on retriable HTTP/API errors (rate limit, 5xx, timeouts).
- Tools: optional single retry for tools that return a “retriable” error (e.g. DB timeout); do not retry on validation errors.

**Complexity:** S–M  
**Rationale:** Retry logic around `generate()` and optionally around `_execute_tool_call`; need a clear notion of “retriable” for tools (e.g. from structured errors from MCP #2).

---

### 4. Tests for the agent

**Impact:** High for maintainability and safe refactors (schema source, prompts, runner logic).

**Tasks:**
- **Unit:** Mock LLM and tool registry; test that with a fixed “model” that returns specific tool_calls or plain text, the runner produces the expected message sequence and return value.
- **Prompt/behavior:** A few tests with a real model (or a deterministic mock) that check e.g. “when game_id is missing, agent calls list_games then ask_user_clarification” or “when question is X and game_id is Y, agent calls search_rules with expected args.”
- **CLI:** Optional smoke test: run ask-agent with a canned question and assert exit 0 and answer non-empty (or contains “not found” when appropriate).

**Complexity:** M  
**Rationale:** Runner is the main unit to test; mocking the LLM is standard; a few integration-style tests give confidence without a heavy harness.

---

### 5. Streaming final answer

**Impact:** Medium; better UX for long answers and clearer “agent is still working” feedback.

**Tasks:**
- Use the LLM’s streaming API when the model is returning the final text (no tool calls); stream tokens to stdout (or callback).
- In interactive mode, stream the final answer the same way; keep “--- Agent ---” and “--- You ---” behavior for clarification turns.

**Complexity:** M  
**Rationale:** OpenAI (and most clients) support streaming; runner and CLI need to handle streamed content and optional progress indicator.

---

### 6. Output validation / guardrails

**Impact:** Medium; reduces risk of the model “making up” citations or format.

**Tasks:**
- Optionally parse the final answer for citation patterns (e.g. “(source_name, p.N)” or “not found”) and log a warning or metric if the model claimed to cite but no pattern found.
- Or: add a lightweight “sanity” step (e.g. one yes/no prompt or rule: “Does this answer contain at least one citation or the phrase ‘not found’?”) and flag or re-prompt if not. Keep it simple to avoid complexity creep.

**Complexity:** M  
**Rationale:** Parsing or a single check is manageable; full “structured output” (e.g. JSON answer) would be a larger change and may not be worth it for this product.

---

### 7. Session / cross-run memory (optional for v1)

**Impact:** Lower for initial 90% goal; high if the product needs multi-turn conversations across runs.

**Tasks:**
- If needed: persist conversation by session_id (e.g. file or DB), load last N turns (or summary) when continuing a session, and pass that into the runner’s message list.
- Optional: summarize long threads before sending to the model to stay under context limits.

**Complexity:** L  
**Rationale:** Requires storage, session boundaries, and possibly summarization; defer unless product explicitly needs cross-run memory.

---

## Suggested order of execution (across all sections)

1. **MCP #1 + Agent #1** — Single source of truth for tool schemas (do together).
2. **MCP #2** — Input validation and structured errors (unblocks Agent #3 retries).
3. **Retrieval #1 + #2** — RRF for hybrid merge; cache embedder and reranker (both S, high impact).
4. **Ingestion #1 + #2 + #3** — Atomic FAISS write; ingest logging; single-writer lock or doc (all S).
5. **MCP #3** — Tool invocation logging.
6. **Agent #2** — Agent observability (logging / optional tracing).
7. **Agent #3** — Retries.
8. **Agent #4** — Tests.
9. **Retrieval #4** — Pipeline observability (latency, counts).
10. **Ingestion #4** — Populate warnings in ingest report.
11. **MCP #4** — Resources (if useful).
12. **Agent #5** — Streaming.
13. **Agent #6** — Output validation / guardrails.
14. **Retrieval #3** — FAISS in-memory (only if you run as a long-lived server).
15. **Ingestion #5 + #6** — Optional: configurable chunking; input caps and PDF error handling.
16. **MCP #5** and **Agent #7** — Only if deployment or product needs (auth, rate limits, session memory).

This order maximizes impact early (schema source, validation, retrieval quality/cost, ingest safety and observability, then agent observability, retries, tests) and defers optional work (resources, streaming, guardrails, in-memory index, chunking config, auth, memory).
