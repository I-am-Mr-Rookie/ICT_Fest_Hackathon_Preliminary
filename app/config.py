"""Application configuration.

Values are read from the environment so the same image can run in different
deployments. Sensible defaults are provided for local development.
"""
import os
import secrets

# Without JWT_SECRET, use a per-process random key rather than a guessable default.
JWT_SECRET = os.getenv("JWT_SECRET") or secrets.token_urlsafe(32)
JWT_ALGORITHM = "HS256"

ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./cowork.db")
