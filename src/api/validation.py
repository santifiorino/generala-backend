from fastapi import HTTPException, status, Header
from sqlmodel import Session, select

from src.config import settings
from src.database import models
from src.database.models import Category, possible_scores


def verify_token(authorization: str | None = Header(None)):
    """
    Verifies if the provided token matches the TOKEN environment variable.
    
    Args:
        authorization: The Authorization header value.
        
    Raises:
        HTTPException: If no token is provided or if the token doesn't match.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header is required"
        )
    
    # Remove 'Bearer ' prefix if present
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    
    if token != settings.TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )


# Helper functions for validation
def validate_category(category: Category):
    """
    Validates if the provided category is a valid game category.

    Args:
        category: The category to validate.

    Raises:
        HTTPException: If the category is invalid.
    """
    if category not in possible_scores:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Invalid category: {category}"
        )

def validate_score(category: Category, score: int):
    """
    Validates if the score is valid for the given category.

    Args:
        category: The category of the score.
        score: The score to validate.

    Raises:
        HTTPException: If the score is not valid for the category.
    """
    if score not in possible_scores.get(category, []):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Invalid score: {score} for category {category}"
        )

def validate_player_exists(player_id: int, session: Session):
    """
    Validates if a player exists in the database.

    Args:
        player_id: The ID of the player to validate.
        session: The database session.

    Raises:
        HTTPException: If the player is not found.
    """
    player = session.get(models.Player, player_id)
    if not player:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"Player with ID {player_id} not found"
        )

def validate_player_in_game(game_id: int, player_id: int, session: Session):
    """
    Validates if a player is part of a specific game.

    Args:
        game_id: The ID of the game.
        player_id: The ID of the player.
        session: The database session.

    Raises:
        HTTPException: If the player is not part of the game.
    """
    game_player = session.exec(
        select(models.GamePlayer).where(
            models.GamePlayer.game_id == game_id,
            models.GamePlayer.player_id == player_id
        )
    ).first()
    
    if not game_player:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Player {player_id} is not part of game {game_id}"
        )

def validate_score_not_exists(game_id: int, player_id: int, category: Category, session: Session):
    """
    Validates that a score does NOT already exist for a given player and category in a game.

    Args:
        game_id: The ID of the game.
        player_id: The ID of the player.
        category: The score category.
        session: The database session.

    Raises:
        HTTPException: If the score already exists.
    """
    existing_score = session.exec(
        select(models.Score).where(
            models.Score.game_id == game_id,
            models.Score.player_id == player_id,
            models.Score.category == category
        )
    ).first()
    
    if existing_score:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, 
            detail=f"Score for category {category} already exists for player {player_id} in game {game_id}"
        )
