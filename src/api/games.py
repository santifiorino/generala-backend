from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import selectinload
from sqlmodel import Session, func, select

from src.api.utils import adjust_datetime
from src.api.validation import (validate_category, validate_player_exists,
                                validate_player_in_game, validate_score,
                                validate_score_not_exists, verify_token)
from src.database import models
from src.database.database import get_session
from src.database.models import possible_scores
from src.logging_config import logger

router = APIRouter(prefix="/games", tags=["games"], dependencies=[Depends(verify_token)])

# Request and Response models
class PlayerRequest(BaseModel):
    id: int
    name: str

class CreateGameRequest(BaseModel):
    players: List[PlayerRequest]

class PatchGameRequest(BaseModel):
    winnerId: int

class ScoreResponse(BaseModel):
    id: int
    category: models.Category
    score: int
    playerId: int
    createdAt: str

class GameResponse(BaseModel):
    id: int
    turn: int
    generalaServida: bool
    createdAt: str
    winnerId: int | None
    players: List[Dict[str, Any]]
    scores: List[ScoreResponse]

class CreateScoreRequest(BaseModel):
    category: models.Category
    score: int

class CreateScoreResponse(BaseModel):
    winnerId: List[int] = []

def _create_game_response(game: models.Game) -> GameResponse:
    """Helper function to create a GameResponse from a Game model."""
    scores_by_player = {}
    for score in game.scores:
        if score.player_id not in scores_by_player:
            scores_by_player[score.player_id] = []
        scores_by_player[score.player_id].append(score)

    players_response = []
    for game_player in game.players:
        player = game_player.player
        player_data = {
            "id": player.id,
            "name": player.name,
            "order": game_player.order,
            **{category.value: None for category in models.Category}
        }
        
        if player.id in scores_by_player:
            for score in scores_by_player[player.id]:
                player_data[score.category.value] = score.score
        
        players_response.append(player_data)

    players_response = sorted(players_response, key=lambda p: p["order"])

    sorted_scores = sorted(game.scores, key=lambda s: s.created_at)
    scores_response = [
        ScoreResponse(
            id=score.id,
            category=score.category,
            score=score.score,
            playerId=score.player_id,
            createdAt=adjust_datetime(score.created_at).isoformat()
        )
        for score in sorted_scores
    ]

    return GameResponse(
        id=game.id,
        players=players_response,
        turn=game.turn,
        winnerId=game.winner_id,
        generalaServida=game.generala_servida,
        createdAt=adjust_datetime(game.created_at).isoformat(),
        scores=scores_response
    )

@router.get("", response_model=List[GameResponse])
async def get_games(session: Session = Depends(get_session)):
    """Get all games"""
    cutoff_date = datetime(2025, 6, 21, 0, 0) # Day of release
    games = session.exec(
        select(models.Game).where(models.Game.created_at >= cutoff_date).order_by(models.Game.created_at.desc()).options(
            selectinload(models.Game.players).selectinload(models.GamePlayer.player),
            selectinload(models.Game.scores)
        )
    ).all()
    return [_create_game_response(game) for game in games]

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_game(request: CreateGameRequest, session: Session = Depends(get_session)):
    """Create a new game with the provided players"""
    logger.info(f"Attempting to create a game with {len(request.players)} players.")
    if len(request.players) < 2:
        logger.warning("Game creation failed: less than 2 players provided.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least 2 players are required to create a game"
        )
    
    # Validate that all players exist in the database
    player_ids = [player.id for player in request.players]
    existing_players = session.exec(
        select(models.Player).where(models.Player.id.in_(player_ids))
    ).all()
    
    if len(existing_players) != len(request.players):
        logger.warning("Game creation failed: some player IDs not found in database.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Players not found in database"
        )
    
    # Create new game
    new_game = models.Game()
    session.add(new_game)
    session.flush()
    
    # Associate players with the game - batch insert
    game_players = []
    for i, player in enumerate(request.players):
        game_players.append(models.GamePlayer(game_id=new_game.id, player_id=player.id, order=i))
    session.add_all(game_players)
    
    logger.info(f"New game created with id: {new_game.id}")
    # Return the created game with player information
    return {
        "id": new_game.id,
    }

@router.get("/{game_id}", response_model=GameResponse)
async def get_game(game_id: int, session: Session = Depends(get_session)):
    """Get a game by its ID with its players and scores"""
    logger.info(f"Fetching game with ID: {game_id}")
    
    game = session.exec(
        select(models.Game)
        .where(models.Game.id == game_id)
        .options(
            selectinload(models.Game.players).selectinload(models.GamePlayer.player),
            selectinload(models.Game.scores)
        )
    ).first()
    
    if not game:
        logger.warning(f"Game with ID {game_id} not found.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game with ID {game_id} not found"
        )
    
    logger.info(f"Successfully fetched game with ID: {game_id}")
    return _create_game_response(game)

@router.patch("/{game_id}", status_code=status.HTTP_200_OK)
async def set_game_winner(game_id: int, request: PatchGameRequest, session: Session = Depends(get_session)):
    """Set the winner of a game, usually to resolve a tie"""
    logger.info(f"Attempting to set winner for game {game_id} to player {request.winnerId}.")

    # Validate game exists
    game = session.exec(
        select(models.Game).where(models.Game.id == game_id)
    ).first()
    if not game:
        logger.warning(f"Setting winner failed: game with ID {game_id} not found.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game with ID {game_id} not found"
        )

    # Validate player exists and is in game
    validate_player_exists(request.winnerId, session)
    validate_player_in_game(game_id, request.winnerId, session)

    game.winner_id = request.winnerId
    
    logger.info(f"Successfully set winner for game {game_id} to player {request.winnerId}.")

    return {"message": f"Winner for game {game_id} set to player {request.winnerId}"}

@router.post("/{game_id}/players/{player_id}/scores", status_code=status.HTTP_201_CREATED)
async def create_score(game_id: int, player_id: int, request: CreateScoreRequest, session: Session = Depends(get_session)) -> CreateScoreResponse:
    """Create a new score for a player in a game"""
    logger.info(f"Attempting to create score for player {player_id} in game {game_id} with category '{request.category}' and score {request.score}.")

    # Validate category and score
    validate_category(request.category)
    validate_score(request.category, request.score)
    
    # Validate game exists
    game = session.exec(
        select(models.Game).where(models.Game.id == game_id)
    ).first()
    if not game:
        logger.warning(f"Score creation failed: game with ID {game_id} not found.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game with ID {game_id} not found"
        )

    # Validate player exists, is in game, and score doesn't exist
    validate_player_exists(player_id, session)
    validate_player_in_game(game_id, player_id, session)
    validate_score_not_exists(game_id, player_id, request.category, session)        
    
    if request.category == models.Category.GENERALA_SERVIDA:
        game.generala_servida = True
        game.winner_id = player_id
        logger.info(f"Generala Servida achieved! Player {player_id} wins game {game_id}.")
        return CreateScoreResponse(winnerId=[player_id])

    new_score = models.Score(
        category=request.category,
        score=request.score,
        game_id=game_id,
        player_id=player_id
    )
    session.add(new_score)

    total_players = session.scalar(
        select(func.count(models.GamePlayer.id)).where(models.GamePlayer.game_id == game_id)
    )
    
    total_categories = len(possible_scores)
    
    # Check if this is the last turn (all players have filled all categories)
    winners = []
    if game.turn >= (total_players * (total_categories - 1)) - 1:
        # Get all scores for all players in this game in one query
        session.flush()
        all_scores = session.exec(
            select(models.Score)
            .where(models.Score.game_id == game_id)
        ).all()
        
        # Calculate total scores for each player
        player_scores = {}
        for score in all_scores:
            if score.player_id not in player_scores:
                player_scores[score.player_id] = 0
            player_scores[score.player_id] += score.score
        
        # Check if there is a tie at the max score
        max_score = max(player_scores.values())
        winners = [p_id for p_id, score in player_scores.items() if score == max_score]
        if len(winners) > 1:
            logger.info(f"There is a tie between players {winners}. Waiting for frontend to decide the winner.")
        else:
            game.winner_id = winners[0]
            logger.info(f"Game {game_id} has ended. Winner is player {winners[0]}.")

    game.turn += 1
    
    logger.info(f"Score created for player {player_id} in game {game_id}")

    return CreateScoreResponse(
        winnerId=winners if 'winners' in locals() else []
    )

@router.delete("/{game_id}/players/{player_id}/scores/{category}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_score(game_id: int, player_id: int, category: models.Category, session: Session = Depends(get_session)):
    """Delete a score for a player in a game"""
    logger.info(f"Attempting to delete score for player {player_id} in game {game_id} for category '{category}'.")

    # Validate category
    validate_category(category)
    
    # Validate game exists
    game = session.exec(
        select(models.Game).where(models.Game.id == game_id)
    ).first()
    if not game:
        logger.warning(f"Score deletion failed: game with ID {game_id} not found.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Game with ID {game_id} not found"
        )

    # Validate player exists
    validate_player_exists(player_id, session)
    
    # Find the score to delete
    score = session.exec(
        select(models.Score).where(
            models.Score.game_id == game_id,
            models.Score.player_id == player_id,
            models.Score.category == category
        )
    ).first()
    
    if not score:
        logger.warning(f"Score deletion failed: score for category {category} not found for player {player_id} in game {game_id}.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Score for category {category} not found"
        )
        
    session.delete(score)
    game.turn -= 1
    
    logger.info(f"Score for category {category} deleted for player {player_id} in game {game_id}.")
    
    return
   


