from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from src.api.validation import verify_token
from src.database import models
from src.database.database import get_session
from src.logging_config import logger

router = APIRouter(prefix="/players", tags=["players"], dependencies=[Depends(verify_token)])


class PlayerResponse(BaseModel):
    id: int
    name: str


@router.get("", response_model=List[PlayerResponse])
async def get_players(session: Session = Depends(get_session)):
    """Get a list of all players."""
    logger.info("Fetching all players.")
    players = session.exec(select(models.Player)).all()
    logger.info(f"Found {len(players)} players.")
    return players 