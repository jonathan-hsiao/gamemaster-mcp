"""Path validation for ingest: allowlist under RULEBOOKS_DIR, exact rulebooks_dir/<game_id>/<source_pdf_name>.pdf."""

from __future__ import annotations

from pathlib import Path


class PathRejectedError(Exception):
    """Raised when a PDF path is outside allowlist or unsafe."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def validate_pdf_path(
    pdf_path: str | Path,
    rulebooks_dir: Path,
    game_id: str | None = None,
) -> Path:
    """
    Resolve path and ensure it is under rulebooks_dir and exactly
    rulebooks_dir/<game_id>/<source_pdf_name>.pdf (flat; no subdirectories).
    Reject symlinks and path traversal.
    Returns resolved Path; raises PathRejectedError if invalid.
    """
    path = Path(pdf_path).resolve()
    root = rulebooks_dir.resolve()

    if not path.exists():
        raise PathRejectedError(f"Path does not exist: {path}")

    if path.is_symlink():
        raise PathRejectedError("Symlinks are not allowed. Use a direct path to the PDF.")

    try:
        rel = path.relative_to(root)
    except ValueError:
        raise PathRejectedError(
            f"PDF path must be under RULEBOOKS_DIR ({root}). Got: {path}"
        )

    if not path.suffix.lower() == ".pdf":
        raise PathRejectedError("File must be a PDF.")

    if not path.is_file():
        raise PathRejectedError("Path must be a file.")

    parts = rel.parts
    if len(parts) != 2:
        raise PathRejectedError(
            f"Path must be exactly rulebooks_dir/<game_id>/<filename>.pdf (flat). Got: {rel}"
        )
    dir_part, file_part = parts
    if game_id is not None and dir_part != game_id:
        raise PathRejectedError(
            f"Path must be under rulebooks_dir/{game_id}/. Got: {rel}"
        )

    return path
