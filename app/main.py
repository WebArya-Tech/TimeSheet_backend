import sys, os
# Ensure the project root is in sys.path for direct script execution
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from contextlib import asynccontextmanager

from app.core.config import settings
from app.api.v1.api import api_router
from app.db.session import init_db, close_db
from app.core.scheduler import setup_scheduler # Import the scheduler setup function

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    
    # Also run our seed script logic 
    from app.db.init_db import init_seed_data
    await init_seed_data()
    
    scheduler = setup_scheduler() # Setup and start the scheduler
    
    yield
    # Shutdown
    await close_db()
    # Shut down the scheduler gracefully if it was started
    try:
        if scheduler:
            scheduler.shutdown()
    except Exception:
        pass

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    openapi_schema["servers"] = [{"url": settings.API_V1_STR}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

app.add_middleware(
    CORSMiddleware,
    # Development: allow all origins to avoid CORS issues from local frontends.
    # Change this to specific origins in production.
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)

# Global exception handler (development) to log tracebacks for easier debugging
from fastapi.responses import JSONResponse
import traceback


@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception):
    # Log full traceback to stdout for developer debugging
    traceback.print_exc()
    # Ensure CORS headers exist on error responses so browser receives them
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Methods": "*",
        "Access-Control-Allow-Headers": "*",
    }
    return JSONResponse(status_code=500, content={"detail": str(exc)}, headers=headers)

@app.get("/")
async def read_root():
    return {"msg": "Welcome to Time Sheet Management System API (MongoDB Edition)"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.SERVER_PORT, reload=True)
