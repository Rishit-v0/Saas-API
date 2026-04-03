from fastapi import FastAPI

from .database import Base, engine
from .routers import auth as auth_router

app = FastAPI(
    title="SaaS API",
    description="AI-powered multi-tenant SaaS backend",
    version="0.1.0",
)


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)


app.include_router(auth_router.router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "0.1.0"}
