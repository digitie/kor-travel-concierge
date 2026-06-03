import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="TripMate Agent API",
    description="FastAPI Backend for YouTube Travel Curation with Gemini",
    version="0.1.0"
)

# CORS Middleware Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify frontend domain e.g., http://localhost:3000
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Welcome to TripMate Agent API", "status": "running"}

@app.get("/api/keywords")
def get_keywords():
    # Placeholder for keyword CRUD
    return []

@app.get("/api/youtubers")
def get_youtubers():
    # Placeholder for YouTuber CRUD
    return []

@app.get("/api/destinations")
def get_destinations():
    # Placeholder for travel destination list
    return []

@app.post("/api/destinations/{destination_id}/deep-research")
def trigger_deep_research(destination_id: int):
    # Placeholder for triggering Gemini Deep Research task
    return {"status": "triggered", "destination_id": destination_id}

@app.get("/api/settings")
def get_settings():
    # Placeholder for settings retrieval
    return {"gemini_engine_version": "gemini-2.0-flash"}

@app.post("/api/settings")
def update_settings(settings: dict):
    # Placeholder for settings update
    return {"status": "updated", "settings": settings}

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
