from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import case
from sqlmodel import Session, func, select

from src.database import models
from src.database.database import get_session
from src.logging_config import logger

router = APIRouter(prefix="/ranking", tags=["ranking"])

class PlayerRankingResponse(BaseModel):
    id: int
    name: str
    max_score: int

class PlayerWinsResponse(BaseModel):
    id: int
    name: str
    wins: int

class GeneralaServidaResponse(BaseModel):
    id: int
    winner_name: str
    created_at: datetime

class RankingResponse(BaseModel):
    wins: List[PlayerWinsResponse]
    score: List[PlayerRankingResponse]
    generalas_servidas: List[GeneralaServidaResponse]

def get_wins_ranking(session: Session) -> List[dict]:
    """Get players ranked by number of wins, sorted from high to low"""
    logger.info("Fetching wins ranking")

    # Subquery to count players per game, only including games with more than 4 players
    player_count_sq = (
        select(
            models.GamePlayer.game_id,
        )
        .group_by(models.GamePlayer.game_id)
        .having(func.count(models.GamePlayer.player_id) > 4)
        .subquery()
    )
    
    # Calculate wins at the database level for valid games
    # A win is 2 points if generala_servida is true, 1 otherwise
    wins_subquery = (
        select(
            models.Game.winner_id,
            func.sum(
                case((models.Game.generala_servida, 2), else_=1)
            ).label("total_wins")
        )
        .join(player_count_sq, models.Game.id == player_count_sq.c.game_id)
        .where(models.Game.winner_id.isnot(None))
        .group_by(models.Game.winner_id)
        .subquery()
    )

    # Join with players to get names and sort
    players_ranking_query = (
        select(
            models.Player.id,
            models.Player.name,
            func.coalesce(wins_subquery.c.total_wins, 0).label("wins"),
        )
        .outerjoin(wins_subquery, models.Player.id == wins_subquery.c.winner_id)
        .order_by(func.coalesce(wins_subquery.c.total_wins, 0).desc())
    )

    results = session.exec(players_ranking_query).all()
    
    return [
        {
            "id": id,
            "name": name,
            "wins": wins
        }
        for id, name, wins in results
    ]

def get_score_ranking(session: Session) -> List[dict]:
    """Get players ranked by max total score in a single game, sorted from high to low"""
    logger.info("Fetching score ranking")

    # Subquery to calculate total score per game for each player
    subquery = (
        select(
            models.Score.player_id,
            models.Score.game_id,
            func.sum(models.Score.score).label("total_score"),
        )
        .group_by(models.Score.player_id, models.Score.game_id)
        .subquery()
    )

    # Main query to find the max score for each player
    score_ranking_query = (
        select(
            models.Player.id,
            models.Player.name,
            func.max(subquery.c.total_score).label("max_score"),
        )
        .join(subquery, models.Player.id == subquery.c.player_id)
        .group_by(models.Player.id, models.Player.name)
        .order_by(func.max(subquery.c.total_score).desc())
    )
    
    results = session.exec(score_ranking_query).all()
    logger.info(f"Found {len(results)} players for score ranking.")
    
    return [
        {
            "id": id,
            "name": name,
            "max_score": max_score if max_score is not None else 0
        }
        for id, name, max_score in results
    ]

def get_generalas_servidas(session: Session) -> List[dict]:
    """Get all games with generala servida, ordered by creation date"""
    logger.info("Fetching generalas servidas")
    games = session.exec(
        select(models.Game)
        .options(selectinload(models.Game.winner))
        .where(models.Game.generala_servida == True)
        .order_by(models.Game.created_at.asc())
    ).all()
    
    logger.info(f"Found {len(games)} games with generala servida.")
    return [
        {
            "id": game.id,
            "winner_name": game.winner.name if game.winner else "N/A",
            "created_at": game.created_at
        }
        for game in games
    ]

@router.get("", response_model=RankingResponse)
async def get_ranking(session: Session = Depends(get_session)):
    """Get the complete ranking including wins, scores, and generalas servidas"""
    logger.info("Fetching complete ranking...")
    
    wins_ranking = get_wins_ranking(session)
    score_ranking = get_score_ranking(session)
    generalas_servidas = get_generalas_servidas(session)
    
    logger.info("Successfully fetched all rankings.")
    
    return {
        "wins": wins_ranking,
        "score": score_ranking,
        "generalas_servidas": generalas_servidas
    }
