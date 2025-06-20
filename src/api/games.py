from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import selectinload
from sqlmodel import Session, func, select

from src.api.validation import (validate_category, validate_player_exists,
                                validate_player_in_game, validate_score,
                                validate_score_not_exists)
from src.database import models
from src.database.database import get_session
from src.database.models import possible_scores
from src.logging_config import logger

router = APIRouter(prefix="/games", tags=["games"])

# Request and Response models
class PlayerRequest(BaseModel):
    id: int
    name: str

class CreateGameRequest(BaseModel):
    players: List[PlayerRequest]

class ScoreResponse(BaseModel):
    id: int
    category: models.Category
    score: int
    player_id: int
    created_at: str

class GameResponse(BaseModel):
    id: int
    turn: int
    generala_servida: bool
    created_at: str
    winner_id: int | None
    players: List[Dict[str, Any]]
    scores: List[ScoreResponse]

class CreateScoreRequest(BaseModel):
    category: models.Category
    score: int

class CreateScoreResponse(BaseModel):
    winner_id: int | None = None

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
    
    # Group scores by player_id for efficient lookup
    scores_by_player = {}
    for score in game.scores:
        if score.player_id not in scores_by_player:
            scores_by_player[score.player_id] = []
        scores_by_player[score.player_id].append(score)

    players_response = []
    for game_player in game.players:
        player = game_player.player
        # Create player response with scores
        player_data = {
            "id": player.id,
            "name": player.name,
            "order": game_player.order,
            **{score: None for score in possible_scores.keys()}
        }
        
        # Add scores to player data
        if player.id in scores_by_player:
            for score in scores_by_player[player.id]:
                player_data[score.category] = score.score
        
        players_response.append(player_data)

    sorted_scores = sorted(game.scores, key=lambda s: s.created_at)
    scores_response = [
        ScoreResponse(
            id=score.id,
            category=score.category,
            score=score.score,
            player_id=score.player_id,
            created_at=score.created_at.isoformat()
        )
        for score in sorted_scores
    ]

    logger.info(f"Successfully fetched game with ID: {game_id}")
    return GameResponse(
        id=game.id,
        players=players_response,
        turn=game.turn,
        winner_id=game.winner_id,
        generala_servida=game.generala_servida,
        created_at=game.created_at.isoformat(),
        scores=scores_response
    )

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
        return CreateScoreResponse(winner_id=player_id)

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
    winner_id = None
    if game.turn >= (total_players * total_categories) - 1:
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
        
        # Find winner
        max_score = 0
        for p_id, total_score in player_scores.items():
            if total_score > max_score:
                max_score = total_score
                winner_id = p_id

        game.winner_id = winner_id
        logger.info(f"Game {game_id} has ended. Winner is player {winner_id}.")

    game.turn += 1
    
    logger.info(f"Score created for player {player_id} in game {game_id}")

    return CreateScoreResponse(
        winner_id=winner_id
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
   




