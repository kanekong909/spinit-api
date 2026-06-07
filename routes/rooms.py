from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from models.database import get_db
from models.db import Room, Spin
from models.schemas import RoomCreate, RoomOut, RoomUpdate, AdminAction, RoomStatusChange
from ws import manager, room_updated_event, status_changed_event
import os

router = APIRouter(prefix="/rooms", tags=["rooms"])

# Server-level admin password — only for global operations (delete any room, etc.)
# Regular room management is now owner-based (no password needed)
SERVER_ADMIN_PW = os.getenv("ADMIN_PASSWORD", "admin123")


def verify_owner(room: Room, owner_id: str):
    """Allow if caller is the room owner OR server admin password was passed as owner_id."""
    if owner_id == SERVER_ADMIN_PW:
        return  # server admin override
    if room.owner_id and room.owner_id != owner_id:
        raise HTTPException(status_code=403, detail="Solo el creador de la sala puede hacer esto")


# --- Create room (anyone) ---
@router.post("/", response_model=RoomOut, status_code=201)
def create_room(data: RoomCreate, db: Session = Depends(get_db)):
    options = [o.strip() for o in data.options if o.strip()]
    # Raffle mode sends a placeholder ['sorteo'] — only enforce min 2 for group mode
    if data.mode == 'group' and len(options) < 2:
        raise HTTPException(status_code=400, detail="Mínimo 2 opciones")
    room = Room(
        name=data.name,
        options=options[:8],
        is_permanent=data.is_permanent,
        owner_id=data.owner_id,
        mode=data.mode,
        prize=data.prize,
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


# --- List rooms ---
@router.get("/", response_model=list[RoomOut])
def list_rooms(db: Session = Depends(get_db)):
    return db.query(Room).order_by(Room.created_at.desc()).limit(50).all()


# --- Get room by ID or code ---
@router.get("/{room_ref}", response_model=RoomOut)
def get_room(room_ref: str, db: Session = Depends(get_db)):
    room = (
        db.query(Room).filter(Room.id == room_ref).first()
        or db.query(Room).filter(Room.code == room_ref.upper()).first()
    )
    if not room:
        raise HTTPException(status_code=404, detail="Sala no encontrada")
    return room


# --- Update room options/name (owner only) ---
@router.patch("/{room_id}", response_model=RoomOut)
async def update_room(room_id: str, data: RoomUpdate, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Sala no encontrada")
    verify_owner(room, data.owner_id)
    if data.name:
        room.name = data.name
    if data.options:
        room.options = [o.strip() for o in data.options if o.strip()][:8]
    if data.mode:
        room.mode = data.mode
    if data.prize is not None:
        room.prize = data.prize
    db.commit()
    db.refresh(room)
    await manager.broadcast_all(room_id, room_updated_event({
        "id": room.id,
        "name": room.name,
        "options": room.options,
        "status": room.status,
    }))
    return room


# --- Change room status (owner only) ---
@router.post("/{room_id}/status", response_model=RoomOut)
async def change_status(room_id: str, data: RoomStatusChange, db: Session = Depends(get_db)):
    valid = ["waiting", "spinning", "revealing", "done"]
    if data.new_status not in valid:
        raise HTTPException(status_code=400, detail=f"Estado inválido. Válidos: {valid}")
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Sala no encontrada")
    verify_owner(room, data.owner_id)
    room.status = data.new_status
    if data.new_status == "spinning":
        # Increment round and clear previous spins for this round
        room.round_number += 1
        db.query(Spin).filter(
            Spin.room_id == room_id,
            Spin.round_number == room.round_number
        ).delete()
    db.commit()
    db.refresh(room)
    await manager.broadcast_all(room_id, status_changed_event(data.new_status))
    return room


# --- Delete room (owner only) ---
# Using POST /delete instead of DELETE to avoid body-in-DELETE issues with some proxies
@router.post("/{room_id}/delete", status_code=204)
def delete_room(room_id: str, data: AdminAction, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Sala no encontrada")
    verify_owner(room, data.owner_id)
    db.delete(room)
    db.commit()