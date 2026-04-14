"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load .env before anything reads os.getenv (e.g. auth.py JWT_SECRET)
load_dotenv()

import app.table_models  # noqa: F401 — registers all SQLModel tables with metadata before init_db
from app.database import init_db
from app.routers import gl, properties, invoices, summary
from app.routers import auth as auth_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure schema is in place on startup (idempotent CREATE IF NOT EXISTS)
    init_db()
    yield


app = FastAPI(
    title="Invoice Classification API",
    description="REST API for the Monarch Invoice Classification Dashboard",
    version="1.0.0",
    lifespan=lifespan,
)

# Allow the Vite dev server to call the API without CORS errors
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(summary.router)
app.include_router(gl.router)
app.include_router(properties.router)
app.include_router(invoices.router)


@app.get("/")
def root():
    return {"message": "Invoice Classification API — see /docs for endpoints"}
