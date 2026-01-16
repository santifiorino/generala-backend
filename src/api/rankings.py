from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import Session, select

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

def fetch_games_with_counts_and_winner(session: Session):
    """Fetch all games with winner name and players count in a single simple query."""
    sql = text("""
        SELECT 
            g.id AS id,
            g.winner_id AS winner_id,
            g.created_at AS created_at,
            g.generala_servida AS generala_servida,
            p.name AS winner_name,
            COUNT(gp.id) AS players_count
        FROM game g
        LEFT JOIN player p ON p.id = g.winner_id
        LEFT JOIN gameplayer gp ON gp.game_id = g.id
        GROUP BY g.id, g.winner_id, g.created_at, g.generala_servida, p.name
        ORDER BY g.created_at ASC
    """)
    return session.exec(sql).all()

@router.get("", response_model=RankingsResponse)
async def get_rankings(session: Session = Depends(get_session)):
    """Get the complete ranking including wins, scores, and generalas servidas"""
    logger.info("Fetching complete ranking with simplified logic...")

    # Player id -> name mapping (used for outputs)
    player_rows = session.exec(select(models.Player.id, models.Player.name)).all()
    player_id_to_name = {player_id: name for player_id, name in player_rows}

    # Single query: games + winner name + players count
    game_rows = fetch_games_with_counts_and_winner(session)

    # Consider only games with >= 5 players and with a winner for rankings
    valid_games = [r for r in game_rows if (getattr(r, "players_count", 0) or 0) >= 5]

    # ---- Wins ranking (Generala Servida counts as 2) with tie-break by first reach time ----
    # Track cumulative wins and the first timestamp each cumulative total was achieved
    cumulative_by_player = {}
    achieved_time_by_player_total = {}
    for r in valid_games:
        winner_id = getattr(r, "winner_id", None)
        if winner_id is None:
            continue
        is_generala_servida = bool(getattr(r, "generala_servida", False))
        increment = 2 if is_generala_servida else 1
        new_total = cumulative_by_player.get(winner_id, 0) + increment
        cumulative_by_player[winner_id] = new_total
        per_player = achieved_time_by_player_total.get(winner_id)
        if per_player is None:
            per_player = {}
            achieved_time_by_player_total[winner_id] = per_player
        if new_total not in per_player:
            per_player[new_total] = getattr(r, "created_at")

    wins_by_player = {player_id: 0 for player_id in player_id_to_name.keys()}
    wins_by_player.update(cumulative_by_player)

    wins_entries = []
    for pid, name in player_id_to_name.items():
        wins = wins_by_player.get(pid, 0)
        achieved_at = achieved_time_by_player_total.get(pid, {}).get(wins) if wins > 0 else None
        wins_entries.append(
            (
                {"id": pid, "name": name, "wins": wins},
                achieved_at,
            )
        )
    wins_entries.sort(key=lambda pair: (-pair[0]["wins"], pair[1] or datetime.max, pair[0]["name"]))
    wins_ranking = [entry for entry, _ in wins_entries]

    # ---- Generalas Servidas list ----
    generalas_servidas = [
        {
            "id": getattr(r, "id"),
            "winnerName": player_id_to_name.get(getattr(r, "winner_id", None), "N/A"),
            "createdAt": adjust_datetime(getattr(r, "created_at")),
        }
        for r in valid_games
        if bool(getattr(r, "generala_servida", False)) and getattr(r, "winner_id", None) is not None
    ]
    generalas_servidas.sort(key=lambda x: x["createdAt"])

    # ---- Scores ranking (max total score by player in a single valid game) ----
    valid_game_ids = [getattr(r, "id") for r in valid_games]
    scores_ranking: List[dict] = []
    if valid_game_ids:
        score_rows = session.exec(
            select(models.Score.player_id, models.Score.game_id, models.Score.score).where(
                models.Score.game_id.in_(valid_game_ids)
            )
        ).all()

        total_by_player_game = {}
        for player_id, game_id, score in score_rows:
            key = (player_id, game_id)
            total_by_player_game[key] = total_by_player_game.get(key, 0) + (score or 0)

        max_by_player = {}
        for (player_id, _game_id), total in total_by_player_game.items():
            current_max = max_by_player.get(player_id, 0)
            if total > current_max:
                max_by_player[player_id] = total

        scores_ranking = sorted(
            (
                {
                    "id": pid,
                    "name": player_id_to_name.get(pid, "N/A"),
                    "maxScore": max_score,
                }
                for pid, max_score in max_by_player.items()
            ),
            key=lambda x: (-x["maxScore"], x["name"]),
        )

    logger.info("Successfully fetched all rankings (simplified).")

    return {
        "wins": wins_ranking,
        "scores": scores_ranking,
        "generalasServidas": generalas_servidas,
    }
