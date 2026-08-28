from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, channels, health, niches, predictions, search, stats, videos

app = FastAPI(title="NicheFinder AI", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(niches.router)
app.include_router(channels.router)
app.include_router(videos.router)
app.include_router(search.router)
app.include_router(predictions.router)
app.include_router(stats.router)
app.include_router(admin.router)
