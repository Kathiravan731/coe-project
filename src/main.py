"""
Main FastAPI application entrypoint.
Serves both the REST API and the modern interactive web application.
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os

from src.database import init_db
from src.routes import router as api_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB tables and triggers on startup
    init_db()
    yield

app = FastAPI(
    title="Loan-Device Return Checklist & Accessory Reconciliation API",
    description="Production-grade pilot system for medical monitoring device reconciliation with zero-PHI storage, explainable rule trails, and tamper-evident event logs.",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware for local testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(api_router, prefix="/api")

# Static assets and SPA frontend
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(os.path.join(STATIC_DIR, "css"), exist_ok=True)
os.makedirs(os.path.join(STATIC_DIR, "js"), exist_ok=True)

app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
