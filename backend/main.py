from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.health import router as health_router
from routes.chat import router as chat_router
from routes.voice import router as voice_router
from database import engine
from models.interview import Base

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Interview Bot API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(chat_router, prefix="/api")
app.include_router(voice_router, prefix="/api")
