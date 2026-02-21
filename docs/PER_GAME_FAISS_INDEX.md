# Per-game FAISS index (known limitation and shape of solution)

## The issue

Dense retrieval uses a **single FAISS index** for all games. At search time we ask FAISS for top-k over the whole index, then **filter** results by the requested `game_id`. So:

- When you have multiple games, the top-k from FAISS can be dominated by chunks from other games. After filtering, the requested game may contribute only a handful of dense hits (or none).
- Hybrid and rerank then see a weak or skewed dense candidate set for that game, so **retrieval quality can drop** when the corpus has many games or one game is a small fraction of the total.

We did it this way for simplicity for MVP (one index file, one code path). FAISS does not support filtering by metadata inside the index.

## Shape of Solution: one index per game

**Goal:** Each game gets its own FAISS index. Search loads only that game’s index, so top-k is already per-game and no post-filter is needed.

**High-level implementation:**

1. **Index path convention** - Derive the index path from `game_id`, e.g. `RULES_STORE_DIR / game_id / "index.faiss"` (and per-game `index_meta.json` if needed). Replace the single global `INDEX_PATH` with this convention wherever the index is read or written.

2. **Ingest** - When ingesting a PDF for a game, load or create the index at that game’s path; add/remove chunk IDs for that game only. Logic (embed, add_with_ids, remove_ids, save, meta) stays the same; only the path is per-game.

3. **Search pipeline** - When running dense search, compute the path for the requested `game_id`. If that file does not exist (e.g. no dense index for that game yet), skip dense or return no dense hits. Remove the post-filter by `game_id` since the index is already per-game.

4. **Server preload** - Preload currently warms one global index. Change to warming only the embedder (and optionally one game’s index if desired); first search per game may do a one-time index load.

5. **Migration** - Document that the new version uses per-game indexes only. Existing users with a single `rules_store/index.faiss` will need to re-ingest to build per-game indexes, or a temporary fallback to the legacy global index can be supported until deprecated.

No change to the FAISS index type (IndexFlatIP + IndexIDMap2) or to E5/embedding logic; only path and routing are per-game.
