"""FastMCP server: tools for list_games, list_sources, search_rules, get_chunks, ingest_pdf, ingest_pdfs."""

from __future__ import annotations

from fastmcp import FastMCP

from gamemaster_mcp.config import EMBED_MODEL_NAME, INDEX_PATH, RERANK_MODEL_NAME
from gamemaster_mcp.mcp_server.tool_logging import ToolLoggingMiddleware
from gamemaster_mcp.mcp_server.resources import (
    get_clarification_game,
    get_clarification_source,
    get_ingest_instructions,
    get_question_answering_instructions,
)
from gamemaster_mcp.mcp_server.instructions import SERVER_INSTRUCTIONS
from gamemaster_mcp.mcp_server.tools_clarification import ask_user_clarification
from gamemaster_mcp.mcp_server.tools_ingest import ingest_pdf, ingest_pdfs
from gamemaster_mcp.mcp_server.tools_search import get_chunks, list_games, list_sources, search_rules


def _preload_models() -> None:
    """Run all first-use init (embedder, reranker, encode, FAISS, ingest path) in the main thread.
    The first search_rules or ingest_pdf(s) from a worker thread was hanging; warming here avoids
    thread-unsafe or first-use-from-worker init (e.g. SentenceTransformer.encode, FAISS)."""
    try:
        from gamemaster_mcp.index.dense_index import (
            _get_embedder,
            load_or_create_index,
        )
        embedder = _get_embedder(EMBED_MODEL_NAME)
        # First encode() in process can block or deadlock when run from a worker thread.
        warmup_emb = embedder.encode(
            ["query: warmup"], normalize_embeddings=True, show_progress_bar=False
        )
        dim = warmup_emb.shape[1]
        # Warm FAISS and index create/load so first ingest_pdf(s) doesn't hang in a worker.
        load_or_create_index(INDEX_PATH, dim)
        # Warm build_embeddings (passage prefix) used by ingest.
        from gamemaster_mcp.index.dense_index import build_embeddings
        build_embeddings(["warmup"], EMBED_MODEL_NAME, show_progress=False)
        if INDEX_PATH.exists():
            from gamemaster_mcp.index.rerank import _get_reranker
            _get_reranker(RERANK_MODEL_NAME)
            # Warm the full search path (FAISS read_index, DB, etc.) in main thread.
            from gamemaster_mcp.search.pipeline import search_rules as pipeline_search_rules
            from gamemaster_mcp.storage import connect_db, list_games as store_list_games
            from gamemaster_mcp.config import DB_PATH
            conn = connect_db(DB_PATH)
            try:
                games = store_list_games(conn)
                if games:
                    pipeline_search_rules(games[0]["game_id"], "warmup", k=1, strategy="hybrid", source_pdf_names="all")
            finally:
                conn.close()
        # Touch ingest deps (PyMuPDF, chunking) so first ingest doesn't pay one-time cost in worker.
        import gamemaster_mcp.ingest  # noqa: F401
    except Exception:  # don't crash server if preload fails
        pass


mcp = FastMCP(
    name="gamemaster",
    instructions=SERVER_INSTRUCTIONS,
)
mcp.add_middleware(ToolLoggingMiddleware())

# Tools: names and schemas come from function signatures and docstrings (FastMCP)
mcp.tool()(list_games)
mcp.tool()(list_sources)
mcp.tool()(search_rules)
mcp.tool()(get_chunks)
mcp.tool()(ask_user_clarification)
mcp.tool()(ingest_pdf)
mcp.tool()(ingest_pdfs)

# Resources: ingest instructions, question-answering procedure, clarification templates (URI must be valid URL)
mcp.resource("resource://gamemaster/ingest_instructions")(get_ingest_instructions)
mcp.resource("resource://gamemaster/question_answering_instructions")(get_question_answering_instructions)
mcp.resource("resource://gamemaster/clarification/game")(get_clarification_game)
mcp.resource("resource://gamemaster/clarification/source")(get_clarification_source)


def main() -> None:
    # Block until models are loaded so the first search_rules request succeeds (no cold-cache hang).
    # This can take 1–2 minutes. The client must wait; if it times out you may see "Connection closed".
    _preload_models()
    mcp.run()


if __name__ == "__main__":
    main()
