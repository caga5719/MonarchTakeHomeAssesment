"""SQLModel engine, session factory, and schema initialization."""

from pathlib import Path
from sqlmodel import SQLModel, Session, create_engine

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "invoice_data.db"
DB_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DB_URL, connect_args={"check_same_thread": False})


def init_db() -> None:
    """Create all tables defined in table_models (IF NOT EXISTS — safe to call on an existing DB)."""
    # table_models must be imported by the caller before init_db() so that
    # SQLModel.metadata knows about all four table classes.
    SQLModel.metadata.create_all(engine)
    print(f"Database initialized at {DB_PATH}")


def get_session():
    """FastAPI dependency: yields a SQLModel Session, auto-closes on exit."""
    with Session(engine) as session:
        yield session
