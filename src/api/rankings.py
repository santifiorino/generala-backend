from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import case
from sqlalchemy import text
from sqlmodel import Session, func, select

from src.api.utils import adjust_datetime
from src.api.validation import verify_token
from src.database import models
from src.database.database import get_session
from src.logging_config import logger

router = APIRouter(prefix="/rankings", tags=["rankings"], dependencies=[Depends(verify_token)])

class ScoreRankingResponse(BaseModel):
    id: int
    name: str
    maxScore: int

class WinsRankingResponse(BaseModel):
    id: int
    name: str
    wins: int

class GeneralasServidasResponses(BaseModel):
    id: int
    winnerName: str
    createdAt: datetime

class RankingsResponse(BaseModel):
    wins: List[WinsRankingResponse]
    scores: List[ScoreRankingResponse]
    generalasServidas: List[GeneralasServidasResponses]

def get_wins_ranking(session: Session) -> List[dict]:
    """Get players ranked by number of wins, sorted from high to low.
    In case of ties, players who reached their current win total first are ranked higher."""
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
    
    # Get all games with their winners and creation time, ordered chronologically
    # Use raw SQL for the complex window function query
    sql_query = text("""
        WITH valid_games AS (
            SELECT g.id, g.winner_id, g.created_at, g.generala_servida
            FROM game g
            INNER JOIN (
                SELECT game_id
                FROM gameplayer 
                GROUP BY game_id 
                HAVING COUNT(player_id) > 4
            ) valid_game_ids ON g.id = valid_game_ids.game_id
            WHERE g.winner_id IS NOT NULL
            ORDER BY g.created_at
        ),
        running_totals AS (
            SELECT 
                winner_id,
                created_at,
                SUM(CASE WHEN generala_servida THEN 2 ELSE 1 END) 
                    OVER (PARTITION BY winner_id ORDER BY created_at 
                          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) as running_wins
            FROM valid_games
        ),
        current_totals AS (
            SELECT 
                winner_id,
                MAX(running_wins) as total_wins
            FROM running_totals
            GROUP BY winner_id
        ),
        first_achievement AS (
            SELECT 
                rt.winner_id,
                ct.total_wins,
                MIN(rt.created_at) as first_achieved_at
            FROM running_totals rt
            INNER JOIN current_totals ct ON rt.winner_id = ct.winner_id 
                AND rt.running_wins = ct.total_wins
            GROUP BY rt.winner_id, ct.total_wins
        )
        SELECT 
            p.id,
            p.name,
            COALESCE(fa.total_wins, 0) as wins,
            fa.first_achieved_at
        FROM player p
        LEFT JOIN first_achievement fa ON p.id = fa.winner_id
        ORDER BY 
            COALESCE(fa.total_wins, 0) DESC,
            fa.first_achieved_at ASC NULLS LAST
    """)
    
    results = session.exec(sql_query).all()
    
    return [
        {
            "id": row.id,
            "name": row.name,
            "wins": row.wins
        }
        for row in results
    ]

def get_scores_ranking(session: Session) -> List[dict]:
    """Get players ranked by max total score in a single game, sorted from high to low"""
    logger.info("Fetching score ranking")

    # Subquery to count players per game, only including games with more than 4 players
    player_count_sq = (
        select(
            models.GamePlayer.game_id,
        )
        .group_by(models.GamePlayer.game_id)
        .having(func.count(models.GamePlayer.player_id) > 4)
        .subquery()
    )

    # Subquery to calculate total score per game for each player, only for valid games
    subquery = (
        select(
            models.Score.player_id,
            models.Score.game_id,
            func.sum(models.Score.score).label("total_score"),
        )
        .join(player_count_sq, models.Score.game_id == player_count_sq.c.game_id)
        .group_by(models.Score.player_id, models.Score.game_id)
        .subquery()
    )

    # Main query to find the max score for each player
    score_rankings_query = (
        select(
            models.Player.id,
            models.Player.name,
            func.max(subquery.c.total_score).label("max_score"),
        )
        .join(subquery, models.Player.id == subquery.c.player_id)
        .group_by(models.Player.id, models.Player.name)
        .order_by(func.max(subquery.c.total_score).desc())
    )
    
    results = session.exec(score_rankings_query).all()
    logger.info(f"Found {len(results)} players for score ranking.")
    
    return [
        {
            "id": id,
            "name": name,
            "maxScore": max_score if max_score is not None else 0
        }
        for id, name, max_score in results
    ]

def get_generalas_servidas(session: Session) -> List[dict]:
    """Get all games with generala servida, ordered by creation date"""
    logger.info("Fetching generalas servidas")
    
    # Subquery to count players per game, only including games with more than 4 players
    player_count_sq = (
        select(
            models.GamePlayer.game_id,
        )
        .group_by(models.GamePlayer.game_id)
        .having(func.count(models.GamePlayer.player_id) > 4)
        .subquery()
    )
    
    games = session.exec(
        select(models.Game)
        .options(selectinload(models.Game.winner))
        .join(player_count_sq, models.Game.id == player_count_sq.c.game_id)
        .where(models.Game.generala_servida == True)
        .order_by(models.Game.created_at.asc())
    ).all()
    
    logger.info(f"Found {len(games)} games with generala servida.")
    return [
        {
            "id": game.id,
            "winnerName": game.winner.name if game.winner else "N/A",
            "createdAt": adjust_datetime(game.created_at)
        }
        for game in games
    ]

@router.get("", response_model=RankingsResponse)
async def get_rankings(session: Session = Depends(get_session)):
    """Get the complete ranking including wins, scores, and generalas servidas"""
    logger.info("Fetching complete ranking...")
    
    wins_ranking = get_wins_ranking(session)
    scores_ranking = get_scores_ranking(session)
    generalas_servidas = get_generalas_servidas(session)
    
    logger.info("Successfully fetched all rankings.")
    
    return {
        "wins": wins_ranking,
        "scores": scores_ranking,
        "generalasServidas": generalas_servidas
    }
