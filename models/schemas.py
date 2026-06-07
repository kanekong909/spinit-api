from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


# --- Room ---

class RoomCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    options: List[str] = Field(..., min_length=1, max_length=8)
    is_permanent: bool = False
    owner_id: Optional[str] = None  # player_id del creador
    mode: str = Field(default='group', pattern='^(group|raffle)$')
    prize: Optional[str] = Field(None, max_length=120)


class RoomUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    options: Optional[List[str]] = Field(None, min_length=2, max_length=8)
    owner_id: str  # must match room.owner_id to authorize edit
    mode: Optional[str] = Field(None, pattern='^(group|raffle)$')
    prize: Optional[str] = Field(None, max_length=120)


class RoomOut(BaseModel):
    id: str
    code: str
    name: str
    options: List[str]
    status: str
    is_permanent: bool
    round_number: int
    owner_id: Optional[str]
    mode: str
    prize: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Player ---

class PlayerJoin(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)
    avatar_style: str = Field(default="adventurer", max_length=40)
    avatar_seed: str = Field(..., max_length=80)


class PlayerOut(BaseModel):
    id: str
    name: str
    avatar_style: str
    avatar_seed: str
    is_online: bool
    joined_at: datetime

    model_config = {"from_attributes": True}


# --- Spin ---

class SpinSubmit(BaseModel):
    result: str  # the option the wheel landed on


class SpinOut(BaseModel):
    id: str
    player_id: str
    round_number: int
    spun_at: datetime
    # result is intentionally omitted until reveal

    model_config = {"from_attributes": True}


# --- Round result ---

class RoundResult(BaseModel):
    winner: str           # opción ganadora
    vote_count: int
    total_players: int
    tiebreak_applied: bool
    all_votes: dict       # option -> count
    # Modo raffle: jugador ganador individual
    raffle_winner_id: Optional[str] = None
    raffle_winner_name: Optional[str] = None
    raffle_winner_avatar_style: Optional[str] = None
    raffle_winner_avatar_seed: Optional[str] = None
    raffle_tiebreak: bool = False  # hubo sorteo entre varios que cayeron en el ganador


# --- Room control (owner-based) ---

class AdminAction(BaseModel):
    owner_id: str  # must match room.owner_id


class RoomStatusChange(BaseModel):
    owner_id: str  # must match room.owner_id
    new_status: str  # waiting | spinning | revealing | done