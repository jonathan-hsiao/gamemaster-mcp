"""SQLite schema for games, sources, chunks, FTS5, and meta."""

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS games (
  game_id     TEXT PRIMARY KEY,
  game_name   TEXT NOT NULL,
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
  source_id       INTEGER PRIMARY KEY,
  game_id         TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
  source_pdf_name TEXT NOT NULL,
  source_name     TEXT NOT NULL,
  pdf_path        TEXT NOT NULL,
  created_at      TEXT NOT NULL,
  UNIQUE(game_id, source_pdf_name)
);

CREATE TABLE IF NOT EXISTS chunks (
  chunk_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id     INTEGER NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
  page_start    INTEGER NOT NULL,
  page_end      INTEGER NOT NULL,
  section_title TEXT,
  text_clean    TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  text_clean,
  content='chunks',
  content_rowid='chunk_id'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
  INSERT INTO chunks_fts(rowid, text_clean) VALUES (new.chunk_id, new.text_clean);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, text_clean) VALUES ('delete', old.chunk_id, old.text_clean);
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, text_clean) VALUES ('delete', old.chunk_id, old.text_clean);
  INSERT INTO chunks_fts(rowid, text_clean) VALUES (new.chunk_id, new.text_clean);
END;

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""
