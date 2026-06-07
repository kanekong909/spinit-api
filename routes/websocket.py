from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from models.database import get_db
from models.db import Room, Player, Spin
from ws import manager
import json

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/{room_id}/{player_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    room_id: str,
    player_id: str,
    db: Session = Depends(get_db),
):
    # Validate room and player exist
    room = db.query(Room).filter(Room.id == room_id).first()
    player = db.query(Player).filter(
        Player.id == player_id, Player.room_id == room_id
    ).first()

    if not room or not player:
        await websocket.close(code=4004)
        return

    await manager.connect(websocket, room_id, player_id)

    # Send current state immediately on connect
    players = db.query(Player).filter(Player.room_id == room_id).all()
    spins_this_round = db.query(Spin).filter(
        Spin.room_id == room_id,
        Spin.round_number == room.round_number
    ).all()
    spun_player_ids = [s.player_id for s in spins_this_round]

    await websocket.send_text(json.dumps({
        "event": "init",
        "room": {
            "id": room.id,
            "code": room.code,
            "name": room.name,
            "options": room.options,
            "status": room.status,
            "round_number": room.round_number,
        },
        "players": [
            {
                "id": p.id,
                "name": p.name,
                "avatar_style": p.avatar_style,
                "avatar_seed": p.avatar_seed,
                "is_online": p.is_online,
                "has_spun": p.id in spun_player_ids,
            }
            for p in players
        ],
        "my_player_id": player_id,
    }))

    try:
        while True:
            # Keepalive: client sends pings
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "ping":
                await websocket.send_text(json.dumps({"event": "pong"}))
    except WebSocketDisconnect:
        manager.disconnect(websocket, room_id)
        # Mark player offline
        db.refresh(player)
        player.is_online = False
        db.commit()
        await manager.broadcast_all(room_id, {
            "event": "player_left",
            "player_id": player_id
        })
