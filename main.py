from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from models.database import init_db, engine
from routes.rooms import router as rooms_router
from routes.players import router as players_router
from routes.spins import router as spins_router
from routes.websocket import router as ws_router
import os

app = FastAPI(
    title="Spinit API",
    description="API para el juego de ruleta grupal",
    version="1.0.0",
)

# Trust Railway's reverse proxy so WebSocket upgrades work correctly
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

# Support comma-separated list of allowed origins, e.g. "https://a.railway.app,https://custom.com"
_raw_origins = os.getenv("FRONTEND_URL", "http://localhost:5173")
ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]
ALLOWED_ORIGINS += ["http://localhost:5173", "http://localhost:4173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"https://.*\.up\.railway\.app",  # all Railway subdomains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rooms_router)
app.include_router(players_router)
app.include_router(spins_router)
app.include_router(ws_router)


@app.on_event("startup")
def on_startup():
    init_db()
    # Safe column migrations — idempotent, safe to run every restart
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE rooms ADD COLUMN IF NOT EXISTS owner_id VARCHAR"))
        conn.execute(text("ALTER TABLE rooms ADD COLUMN IF NOT EXISTS mode VARCHAR DEFAULT 'group'"))
        conn.execute(text("ALTER TABLE rooms ADD COLUMN IF NOT EXISTS prize VARCHAR(120)"))
        conn.commit()
    print("✅ Base de datos lista")


@app.get("/health")
def health():
    return {"status": "ok", "service": "spinit-api"}


@app.get("/")
def root():
    return {"message": "Spinit API v1.0 — /docs para documentación"}