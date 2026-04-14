from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.middleware.rate_limit import RateLimitMiddleware

from .database import Base, engine
from .routers import auth as auth_router
from .routers import notes as notes_router
from .routers import tenants as tenant_router


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


API_PREFIX = "/api/v1"

app.include_router(auth_router.router, prefix=f"{API_PREFIX}", tags=["Authentication"])
app.include_router(tenant_router.router, prefix=f"{API_PREFIX}", tags=["Tenants"])
app.include_router(notes_router.router, prefix=f"{API_PREFIX}", tags=["Notes"])


@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "0.1.0"}


@app.get("/")
async def root():
    return {
        "name": "SaaS API",
        "version": "1.0.0",
        "api_prefix": API_PREFIX,
        "docs": "/docs",
    }


# Add rate limiting middleware
app.add_middleware(
    RateLimitMiddleware,
    request_per_window=60,
    window_seconds=60,
    exclude_paths=["/", "/docs", "/openapi.json", "/health", "/api/v1/auth/token"],
)
