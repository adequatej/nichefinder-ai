from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, niches

app = FastAPI(title="NicheFinder AI", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(niches.router)
