from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer, JSON, Text
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime
import uuid

Base = declarative_base()

def gen_id():
    return str(uuid.uuid4())

def gen_code():
    import random, string
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


class Room(Base):
    __tablename__ = "rooms"

    id = Column(String, primary_key=True, default=gen_id)
    code = Column(String(6), unique=True, nullable=False, default=gen_code)
    name = Column(String(80), nullable=False)
    options = Column(JSON, nullable=False, default=list)
    status = Column(String(20), nullable=False, default="waiting")
    # waiting → spinning → revealing → done
    is_permanent = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    round_number = Column(Integer, default=1)
    owner_id = Column(String, nullable=True)   # player_id del creador
    mode = Column(String(20), nullable=False, default="group")  # group | raffle
    prize = Column(String(120), nullable=True)  # texto del premio (solo modo raffle)

    players = relationship("Player", back_populates="room", cascade="all, delete-orphan")
    spins = relationship("Spin", back_populates="room", cascade="all, delete-orphan")


class Player(Base):
    __tablename__ = "players"

    id = Column(String, primary_key=True, default=gen_id)
    room_id = Column(String, ForeignKey("rooms.id"), nullable=False)
    name = Column(String(40), nullable=False)
    avatar_style = Column(String(40), nullable=False, default="adventurer")
    avatar_seed = Column(String(80), nullable=False)
    is_online = Column(Boolean, default=True)
    joined_at = Column(DateTime, default=datetime.utcnow)

    room = relationship("Room", back_populates="players")
    spins = relationship("Spin", back_populates="player", cascade="all, delete-orphan")


class Spin(Base):
    __tablename__ = "spins"

    id = Column(String, primary_key=True, default=gen_id)
    room_id = Column(String, ForeignKey("rooms.id"), nullable=False)
    player_id = Column(String, ForeignKey("players.id"), nullable=False)
    round_number = Column(Integer, nullable=False, default=1)
    result = Column(String(80), nullable=True)   # hidden until reveal
    spin_order = Column(Integer, nullable=False)  # order of spin (for tiebreak)
    spun_at = Column(DateTime, default=datetime.utcnow)

    room = relationship("Room", back_populates="spins")
    player = relationship("Player", back_populates="spins")
