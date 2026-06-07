from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from models.database import get_db
from models.db import Room, Player
from models.schemas import PlayerJoin, PlayerOut
from ws import manager, player_joined_event, player_left_event

router = APIRouter(prefix="/rooms/{room_id}/players", tags=["players"])


@router.post("/", response_model=PlayerOut, status_code=201)
async def join_room(room_id: str, data: PlayerJoin, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Sala no encontrada")
    if room.status == "done":
        raise HTTPException(status_code=400, detail="Esta sala ya terminó")

    # Check if player with this name already exists in the room (online or offline)
    existing = db.query(Player).filter(
        Player.room_id == room_id,
        Player.name == data.name,
    ).first()

    if existing:
        if existing.is_online:
            # Someone else is already connected with this name
            raise HTTPException(status_code=409, detail="Ya hay un jugador conectado con ese nombre")
        # Returning player — mark online and update avatar in case they changed it
        existing.is_online = True
        existing.avatar_style = data.avatar_style
        existing.avatar_seed = data.avatar_seed
        db.commit()
        db.refresh(existing)
        await manager.broadcast_all(room_id, player_joined_event({
            "id": existing.id,
            "name": existing.name,
            "avatar_style": existing.avatar_style,
            "avatar_seed": existing.avatar_seed,
            "is_online": True,
        }))
        return existing

    # New player
    player = Player(
        room_id=room_id,
        name=data.name,
        avatar_style=data.avatar_style,
        avatar_seed=data.avatar_seed,
    )
    db.add(player)
    db.commit()
    db.refresh(player)

    await manager.broadcast_all(room_id, player_joined_event({
        "id": player.id,
        "name": player.name,
        "avatar_style": player.avatar_style,
        "avatar_seed": player.avatar_seed,
        "is_online": True,
    }))
    return player


@router.get("/", response_model=list[PlayerOut])
def list_players(room_id: str, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Sala no encontrada")
    return db.query(Player).filter(Player.room_id == room_id).all()


@router.delete("/{player_id}", status_code=204)
async def leave_room(room_id: str, player_id: str, db: Session = Depends(get_db)):
    player = db.query(Player).filter(
        Player.id == player_id,
        Player.room_id == room_id
    ).first()
    if not player:
        raise HTTPException(status_code=404, detail="Jugador no encontrado")
    player.is_online = False
    db.commit()
    await manager.broadcast_all(room_id, player_left_event(player_id))