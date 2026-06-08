from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from models.database import get_db
from models.db import Room, Player, Spin
from models.schemas import SpinSubmit, SpinOut, RoundResult
from ws import manager, player_spun_event, round_result_event
import random

router = APIRouter(prefix="/rooms/{room_id}/spins", tags=["spins"])


def _get_valid_options(room: Room, db: Session) -> list[str]:
    """
    Modo group  → opciones definidas por el admin (room.options)
    Modo raffle → nombres de los jugadores online (la ruleta ES la lista de participantes)
    """
    if room.mode == "raffle":
        players = db.query(Player).filter(
            Player.room_id == room.id,
            Player.is_online == True
        ).order_by(Player.joined_at).all()
        return [p.name for p in players]
    return room.options


@router.post("/{player_id}", response_model=SpinOut, status_code=201)
async def submit_spin(
    room_id: str,
    player_id: str,
    data: SpinSubmit,
    db: Session = Depends(get_db)
):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Sala no encontrada")
    if room.status != "spinning":
        raise HTTPException(status_code=400, detail="La ronda no está en curso")

    player = db.query(Player).filter(
        Player.id == player_id, Player.room_id == room_id
    ).first()
    if not player:
        raise HTTPException(status_code=404, detail="Jugador no encontrado")

    existing = db.query(Spin).filter(
        Spin.player_id == player_id,
        Spin.round_number == room.round_number
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Ya giraste en esta ronda")

    # Validate against correct options for the mode
    valid_options = _get_valid_options(room, db)

    if room.mode == "raffle":
        # In raffle mode, valid results are player names — also accept the spinning player's own name
        # This is more permissive to handle race conditions between frontend/backend player lists
        all_player_names = [p.name for p in db.query(Player).filter(
            Player.room_id == room_id, Player.is_online == True
        ).all()]
        if data.result not in all_player_names:
            raise HTTPException(status_code=400, detail=f"El sector '{data.result}' no corresponde a ningún jugador en la sala")
    else:
        if data.result not in valid_options:
            raise HTTPException(status_code=400, detail=f"Opción inválida: '{data.result}'. Opciones válidas: {valid_options}")

    spins_so_far = db.query(Spin).filter(
        Spin.room_id == room_id,
        Spin.round_number == room.round_number
    ).count()

    spin = Spin(
        room_id=room_id,
        player_id=player_id,
        round_number=room.round_number,
        result=data.result,
        spin_order=spins_so_far + 1,
    )
    db.add(spin)
    db.commit()
    db.refresh(spin)

    await manager.broadcast_all(room_id, player_spun_event(player_id, spin.spin_order))

    online_count = db.query(Player).filter(
        Player.room_id == room_id, Player.is_online == True
    ).count()
    spun_count = db.query(Spin).filter(
        Spin.room_id == room_id,
        Spin.round_number == room.round_number
    ).count()

    if spun_count >= online_count:
        result = _calculate_result(db, room_id, room.round_number, room.mode, valid_options)
        room.status = "revealing"
        db.commit()
        await manager.broadcast_all(room_id, round_result_event(result.model_dump()))

    return spin


def _calculate_result(
    db: Session,
    room_id: str,
    round_number: int,
    mode: str = "group",
    valid_options: list = None
) -> RoundResult:
    spins = db.query(Spin).filter(
        Spin.room_id == room_id,
        Spin.round_number == round_number
    ).all()

    # Map: sector_name → list of spins that landed there
    votes: dict[str, list] = {}
    for spin in spins:
        votes.setdefault(spin.result, [])
        votes[spin.result].append(spin)

    vote_counts = {opt: len(lst) for opt, lst in votes.items()}

    # ── RAFFLE MODE ──────────────────────────────────────────────────────────
    # The wheel sectors ARE the player names.
    # Logic: system picks a random winning sector → the player who landed there wins.
    # If nobody landed on the chosen sector, pick from sectors that DID get votes.
    if mode == "raffle":
        all_sectors = valid_options or list(votes.keys())

        # Try a random sector; if empty, fall back to sectors with votes
        chosen_sector = random.choice(all_sectors)
        if chosen_sector not in votes or not votes[chosen_sector]:
            # Fall back: pick from sectors that actually got votes
            sectors_with_votes = [s for s in all_sectors if s in votes and votes[s]]
            chosen_sector = random.choice(sectors_with_votes) if sectors_with_votes else random.choice(all_sectors)

        winning_spins  = votes.get(chosen_sector, [])
        raffle_tiebreak = len(winning_spins) > 1  # multiple players landed on same sector

        raffle_winner_id = raffle_winner_name = raffle_winner_avatar_style = raffle_winner_avatar_seed = None
        if winning_spins:
            chosen_spin   = random.choice(winning_spins)
            winner_player = db.query(Player).filter(Player.id == chosen_spin.player_id).first()
            if winner_player:
                raffle_winner_id           = winner_player.id
                raffle_winner_name         = winner_player.name
                raffle_winner_avatar_style = winner_player.avatar_style
                raffle_winner_avatar_seed  = winner_player.avatar_seed

        return RoundResult(
            winner=chosen_sector,          # the winning sector (a player name)
            vote_count=len(winning_spins),
            total_players=len(spins),
            tiebreak_applied=False,        # not applicable in raffle
            all_votes=vote_counts,
            raffle_winner_id=raffle_winner_id,
            raffle_winner_name=raffle_winner_name,
            raffle_winner_avatar_style=raffle_winner_avatar_style,
            raffle_winner_avatar_seed=raffle_winner_avatar_seed,
            raffle_tiebreak=raffle_tiebreak,
        )

    # ── GROUP MODE ────────────────────────────────────────────────────────────
    # Most-voted option wins; random tiebreak.
    max_votes     = max(vote_counts.values())
    tied_options  = [opt for opt, count in vote_counts.items() if count == max_votes]
    tiebreak_applied = len(tied_options) > 1
    winning_option   = random.choice(tied_options)

    return RoundResult(
        winner=winning_option,
        vote_count=max_votes,
        total_players=len(spins),
        tiebreak_applied=tiebreak_applied,
        all_votes=vote_counts,
        raffle_winner_id=None,
        raffle_winner_name=None,
        raffle_winner_avatar_style=None,
        raffle_winner_avatar_seed=None,
        raffle_tiebreak=False,
    )


@router.get("/result", response_model=RoundResult)
def get_round_result(room_id: str, round_number: int = None, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Sala no encontrada")
    if room.status not in ("revealing", "done"):
        raise HTTPException(status_code=400, detail="Resultados aún no disponibles")
    rn = round_number or room.round_number
    valid = _get_valid_options(room, db)
    return _calculate_result(db, room_id, rn, room.mode, valid)


@router.get("/", response_model=list[SpinOut])
def list_spins(room_id: str, db: Session = Depends(get_db)):
    return db.query(Spin).filter(Spin.room_id == room_id).all()