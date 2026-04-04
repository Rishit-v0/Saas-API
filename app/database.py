import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

load_dotenv()  # Load environment variables from .env file

# SQLAlchemy connection string — same info as Django DATABASES setting
# Format: postgresql://user:password@host:port/dbname
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://rishit:DATABASE_PASSWORD@localhost:5432/saas_db",
)

# create_engine creates the connection pool to PostgreSQL
# pool_pre_ping=True tests connections before using them — prevents stale connection errors
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# SessionLocal is a factory for creating new SQLAlchemy sessions
# Each request gets its own session — opened at start, closed at end

# autocommit=False means changes aren't saved until you explicitly commit
# autoflush=False means SQLAlchemy won't auto-sync before queries
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class that all SQLAlchemy models inherit from
# Equivalent of Django's models.Model
Base = declarative_base()


# Dependency function — FastAPI's way of injecting a DB session into routes
# yield gives the session to the route, finally ensures it closes after
# This is equivalent of Django's ORM automatically managing connections
def get_db():
    db = SessionLocal()  # Create a new DB session
    try:
        yield db  # Provide the session to the route
    finally:
        db.close()  # Ensure the session is closed after the request
