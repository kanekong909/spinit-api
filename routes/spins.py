from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from models.database import get_db
from models.db import Room, Player, Spin
from models.schemas import SpinSubmit, SpinOut, RoundResult
from ws import manager, player_spun_event, round_result_event
import random

router = APIRouter(prefix="/rooms/{room_id}/spins", tags=["spins"])


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

    if data.result not in room.options:
        raise HTTPException(status_code=400, detail="Opción inválida")

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

    # Check if all online players have spun
    online_count = db.query(Player).filter(
        Player.room_id == room_id, Player.is_online == True
    ).count()
    spun_count = db.query(Spin).filter(
        Spin.room_id == room_id,
        Spin.round_number == room.round_number
    ).count()

    if spun_count >= online_count:
        result = _calculate_result(db, room_id, room.round_number, room.mode)
        room.status = "revealing"
        db.commit()
        await manager.broadcast_all(room_id, round_result_event(result.model_dump()))

    return spin


def _calculate_result(db: Session, room_id: str, round_number: int, mode: str = "group") -> RoundResult:
    spins = db.query(Spin).filter(
        Spin.room_id == room_id,
        Spin.round_number == round_number
    ).all()

    # Count votes per option
    votes: dict[str, list] = {}
    for spin in spins:
        votes.setdefault(spin.result, [])
        votes[spin.result].append(spin)

    vote_counts = {opt: len(lst) for opt, lst in votes.items()}
    max_votes = max(vote_counts.values())
    tied_options = [opt for opt, count in vote_counts.items() if count == max_votes]
    tiebreak_applied = len(tied_options) > 1

    # Winning option (random among tied)
    winning_option = random.choice(tied_options)

    # --- Raffle mode: pick an individual winner ---
    raffle_winner_id = None
    raffle_winner_name = None
    raffle_winner_avatar_style = None
    raffle_winner_avatar_seed = None
    raffle_tiebreak = False

    if mode == "raffle":
        # Players who landed on the winning option
        winning_spins = votes.get(winning_option, [])
        raffle_tiebreak = len(winning_spins) > 1

        if winning_spins:
            chosen_spin = random.choice(winning_spins)
            winner_player = db.query(Player).filter(Player.id == chosen_spin.player_id).first()
            if winner_player:
                raffle_winner_id = winner_player.id
                raffle_winner_name = winner_player.name
                raffle_winner_avatar_style = winner_player.avatar_style
                raffle_winner_avatar_seed = winner_player.avatar_seed

    return RoundResult(
        winner=winning_option,
        vote_count=max_votes,
        total_players=len(spins),
        tiebreak_applied=tiebreak_applied,
        all_votes=vote_counts,
        raffle_winner_id=raffle_winner_id,
        raffle_winner_name=raffle_winner_name,
        raffle_winner_avatar_style=raffle_winner_avatar_style,
        raffle_winner_avatar_seed=raffle_winner_avatar_seed,
        raffle_tiebreak=raffle_tiebreak,
    )


@router.get("/result", response_model=RoundResult)
def get_round_result(room_id: str, round_number: int = None, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Sala no encontrada")
    if room.status not in ("revealing", "done"):
        raise HTTPException(status_code=400, detail="Resultados aún no disponibles")
    rn = round_number or room.round_number
    return _calculate_result(db, room_id, rn, room.mode)


@router.get("/", response_model=list[SpinOut])
def list_spins(room_id: str, db: Session = Depends(get_db)):
    return db.query(Spin).filter(Spin.room_id == room_id).all()
