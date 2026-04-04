from fastapi import FastAPI
from contextlib import asynccontextmanager

from .database import Base, engine
from .routers import auth as auth_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield

app = FastAPI(
    title="SaaS API",
    lifespan=lifespan,
    description="AI-powered multi-tenant SaaS backend",
    version="0.1.0",
)


app.include_router(auth_router.router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "0.1.0"}
