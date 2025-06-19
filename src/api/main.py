import logging
import time

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from src.api.errors import http_exception_handler, sqlalchemy_exception_handler
from src.api.games import router as games_router
from src.api.ranking import router as ranking_router
from src.config import settings
from src.database import models  # Import models to register them with SQLModel
from src.database.database import create_db_and_tables, get_session
from src.logging_config import setup_logging

logger = logging.getLogger("generala")

app = FastAPI(
    title=settings.PROJECT_NAME
)

# Exception Handlers
app.add_exception_handler(Exception, http_exception_handler)
app.add_exception_handler(SQLAlchemyError, sqlalchemy_exception_handler)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=settings.CORS_ALLOW_HEADERS,
)

# Include routers
app.include_router(games_router)
app.include_router(ranking_router)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Middleware to log requests and responses."""
    start_time = time.time()
    logger.info(f"Request: {request.method} {request.url.path}")
    response = await call_next(request)
    process_time = (time.time() - start_time) * 1000
    logger.info(f"Response: {response.status_code} ({process_time:.2f}ms)")
    return response

@app.on_event("startup")
async def startup_event():
    """Initialize database and logging on startup"""
    setup_logging()
    logger.info("Starting up Generala API...")
    create_db_and_tables()

@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    """Health check endpoint to verify the API is running."""
    logger.info("Health check endpoint called")
    return {"message": "Generala API is running"}

@app.get("/test-db", status_code=status.HTTP_200_OK)
async def test_database(session: Session = Depends(get_session)):
    """Test endpoint to verify database connection and tables"""
    # The connection is handled by the get_session dependency.
    # If it fails, the sqlalchemy_exception_handler will catch it.
    logger.info("Testing database connection...")
    players = session.exec(select(models.Player)).all()
    logger.info(f"Successfully connected to DB and found {len(players)} players.")
    return {
        "message": "Database connection successful",
        "players_count": len(players),
    }
