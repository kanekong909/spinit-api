from fastapi import WebSocket
from typing import Dict, List
import json
import asyncio


class ConnectionManager:
    """
    Manages WebSocket connections grouped by room_id.
    Each room has a list of (player_id, websocket) tuples.
    """

    def __init__(self):
        # room_id -> list of {"player_id": str, "ws": WebSocket}
        self.rooms: Dict[str, List[dict]] = {}

    async def connect(self, websocket: WebSocket, room_id: str, player_id: str):
        await websocket.accept()
        if room_id not in self.rooms:
            self.rooms[room_id] = []
        self.rooms[room_id].append({"player_id": player_id, "ws": websocket})

    def disconnect(self, websocket: WebSocket, room_id: str):
        if room_id in self.rooms:
            self.rooms[room_id] = [
                c for c in self.rooms[room_id] if c["ws"] != websocket
            ]
            if not self.rooms[room_id]:
                del self.rooms[room_id]

    async def broadcast(self, room_id: str, message: dict, exclude_ws: WebSocket = None):
        """Send a message to all connections in a room."""
        if room_id not in self.rooms:
            return
        dead = []
        for conn in self.rooms[room_id]:
            if conn["ws"] == exclude_ws:
                continue
            try:
                await conn["ws"].send_text(json.dumps(message))
            except Exception:
                dead.append(conn)
        for d in dead:
            self.rooms[room_id].remove(d)

    async def broadcast_all(self, room_id: str, message: dict):
        await self.broadcast(room_id, message, exclude_ws=None)

    def room_player_count(self, room_id: str) -> int:
        return len(self.rooms.get(room_id, []))


manager = ConnectionManager()


# --- Event helpers ---

def player_joined_event(player: dict) -> dict:
    return {"event": "player_joined", "player": player}

def player_left_event(player_id: str) -> dict:
    return {"event": "player_left", "player_id": player_id}

def player_spun_event(player_id: str, spin_order: int) -> dict:
    # result is intentionally NOT included
    return {"event": "player_spun", "player_id": player_id, "spin_order": spin_order}

def round_started_event(round_number: int, options: list) -> dict:
    return {"event": "round_started", "round_number": round_number, "options": options}

def round_result_event(result: dict) -> dict:
    return {"event": "round_result", "result": result}

def room_updated_event(room: dict) -> dict:
    return {"event": "room_updated", "room": room}

def status_changed_event(status: str) -> dict:
    return {"event": "status_changed", "status": status}
