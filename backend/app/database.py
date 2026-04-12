"""SQLite connection, session factory, and schema initialization."""

from pathlib import Path
import sqlite3

# The DB lives one level above the backend/ directory so it stays at the repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "invoice_data.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_connection() -> sqlite3.Connection:
    """Return a new SQLite connection with row_factory set for dict-like access."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    """Create all tables (if not already present) by running schema.sql."""
    ddl = SCHEMA_PATH.read_text()
    with get_connection() as conn:
        conn.executescript(ddl)
    print(f"Database initialized at {DB_PATH}")


if __name__ == "__main__":
    init_db()
