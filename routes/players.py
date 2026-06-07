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

    # Prevent duplicate names in same room
    existing = db.query(Player).filter(
        Player.room_id == room_id,
        Player.name == data.name,
        Player.is_online == True
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Ya hay un jugador con ese nombre en esta sala")

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
