from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers.auth.auth_routes import router as auth_router
from routers.patient.patient_routes import router as patient_router
from routers.profile.profile_routes import router as profile_router
from routers.diary.diary_routes import router as diary_router
from routers.summaries.summaries_routes import router as summaries_router
from routers.chemo.chemo_routes import router as chemo_router
from routers.chat.chat_routes import router as chat_router

app = FastAPI()

# CORS
_default_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
_env_origins = os.getenv("CORS_ORIGINS")
allow_origins = [o.strip() for o in _env_origins.split(",")] if _env_origins else _default_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(patient_router)
app.include_router(profile_router)
app.include_router(diary_router)
app.include_router(summaries_router)
app.include_router(chemo_router)
app.include_router(chat_router)

@app.get("/health")
async def health():
    return {"status": "ok"}
