"""Environment and settings. Load .env and expose paths, caps, and feature flags."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (cwd when running from repo)
load_dotenv(override=False)

# --- Hugging Face cache: set defaults in process so server has a predictable cache location ---
# User can still override via .env (load_dotenv runs first). setdefault leaves existing values.
_hf_cache_root = Path(os.getenv("HF_HOME", Path.cwd() / ".cache" / "huggingface")).resolve()
os.environ.setdefault("HF_HOME", str(_hf_cache_root))
os.environ.setdefault("TRANSFORMERS_CACHE", str(_hf_cache_root / "transformers"))
os.environ.setdefault("HF_HUB_CACHE", str(_hf_cache_root / "hub"))

# --- Paths (relative to cwd or absolute) ---
RULEBOOKS_DIR = Path(os.getenv("RULEBOOKS_DIR", "rulebooks")).resolve()
RULES_STORE_DIR = Path(os.getenv("RULES_STORE_DIR", "rules_store")).resolve()
DB_PATH = RULES_STORE_DIR / "rules.db"
INDEX_PATH = RULES_STORE_DIR / "index.faiss"
META_PATH = RULES_STORE_DIR / "index_meta.json"

# --- Ingest validation (brief: text density threshold) ---
TEXT_DENSITY_MIN_CHARS_PER_PAGE = int(os.getenv("TEXT_DENSITY_MIN_CHARS_PER_PAGE", "100"))

# --- get_chunks caps (brief: at most 20 chunks, 4000 chars per chunk) ---
GET_CHUNKS_MAX_CHUNKS = int(os.getenv("GET_CHUNKS_MAX_CHUNKS", "20"))
GET_CHUNKS_MAX_CHARS = int(os.getenv("GET_CHUNKS_MAX_CHARS", "4000"))

# --- search_rules: max candidates from sparse (FTS) and dense (FAISS) before merge/rerank ---
SEARCH_K_SPARSE = int(os.getenv("SEARCH_K_SPARSE", "50"))
SEARCH_K_DENSE = int(os.getenv("SEARCH_K_DENSE", "50"))

# --- Models (defaults from brief) ---
EMBED_MODEL_NAME = os.getenv("EMBED_MODEL", "intfloat/e5-small-v2")
RERANK_MODEL_NAME = os.getenv("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")

# --- Agent LLM (thin agent) ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")

# --- Agent debug logs (--debug); folder at project root, created on first write ---
AGENT_DEBUG_LOG_DIR = Path(os.getenv("AGENT_DEBUG_LOG_DIR", "logs")).resolve()

# --- Long-lived session: sliding context, inner loop cap, quit trigger ---
CONTEXT_MAX_TURNS = int(os.getenv("GAMEMASTER_CONTEXT_MAX_TURNS", "50"))
INNER_MAX_TURNS = int(os.getenv("GAMEMASTER_INNER_MAX_TURNS", "20"))
QUIT_TRIGGER = os.getenv("GAMEMASTER_QUIT_TRIGGER", "/quit").strip()
