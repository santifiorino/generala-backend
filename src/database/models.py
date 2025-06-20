from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import validator
from sqlmodel import Field, Relationship, SQLModel


class Player(SQLModel, table=True):
    """Represents a player in the game."""
    id: Optional[int] = Field(default=None, primary_key=True, description="Player's unique ID")
    name: str = Field(
        description="Player's name",
        sa_column_kwargs={"unique": True}
    )
    
    won_games: List["Game"] = Relationship(back_populates="winner")
    games: List["GamePlayer"] = Relationship(back_populates="player")
    scores: List["Score"] = Relationship(back_populates="player")
    
    @property
    def wins(self) -> int:
        """Calculate total wins for the player, with a bonus for 'generala servida'."""
        total_wins = 0
        for game in self.won_games:
            if game.generala_servida:
                total_wins += 2  # Generala Servida counts as double points
            else:
                total_wins += 1
        return total_wins


class Game(SQLModel, table=True):
    """Represents a single game of Generala."""
    id: Optional[int] = Field(default=None, primary_key=True, description="Game's unique ID")
    turn: int = Field(default=0, ge=0, description="Current turn number in the game")
    generala_servida: bool = Field(default=False, description="Whether the game was won with a 'generala servida'")
    created_at: datetime = Field(default_factory=datetime.now, description="Timestamp when the game was created")
    winner_id: Optional[int] = Field(default=None, foreign_key="player.id", description="ID of the winning player")
    
    winner: Optional["Player"] = Relationship(back_populates="won_games")
    players: List["GamePlayer"] = Relationship(
        back_populates="game",
        sa_relationship_kwargs={"order_by": "GamePlayer.order"}
    )
    scores: List["Score"] = Relationship(back_populates="game")


class GamePlayer(SQLModel, table=True):
    """Association table for the many-to-many relationship between Game and Player."""
    id: Optional[int] = Field(default=None, primary_key=True)
    
    game_id: int = Field(foreign_key="game.id", description="ID of the game")
    player_id: int = Field(foreign_key="player.id", description="ID of the player")
    order: int = Field(default=0, description="Order of the player in the game")
    
    game: "Game" = Relationship(back_populates="players")
    player: "Player" = Relationship(back_populates="games")

class Category(str, Enum):
    """Enum for the different scoring categories in Generala."""
    ONE = "1"
    TWO = "2"
    THREE = "3"
    FOUR = "4"
    FIVE = "5"
    SIX = "6"
    ESCALERA = "Escalera"
    FULL = "Full"
    POKER = "Poker"
    GENERALA = "Generala"
    GENERALA_DOBLE = "Generala Doble"
    GENERALA_SERVIDA = "Generala Servida"

possible_scores = {
    Category.ONE: [0, 1, 2, 3, 4, 5],
    Category.TWO: [0, 2, 4, 6, 8, 10],
    Category.THREE: [0, 3, 6, 9, 12, 15],
    Category.FOUR: [0, 4, 8, 12, 16, 20],
    Category.FIVE: [0, 5, 10, 15, 20, 25],
    Category.SIX: [0, 6, 12, 18, 24, 30],
    Category.ESCALERA: [0, 20, 25],
    Category.FULL: [0, 30, 35],
    Category.POKER: [0, 40, 45],
    Category.GENERALA: [0, 50],
    Category.GENERALA_DOBLE: [0, 100],
}

class Score(SQLModel, table=True):
    """Represents a player's score in a specific category for a game."""
    id: Optional[int] = Field(default=None, primary_key=True)
    category: Category = Field(description="Scoring category")
    score: int = Field(default=0, ge=0, description="Points scored in the category")
    created_at: datetime = Field(default_factory=datetime.now, description="Timestamp when the score was created")
    game_id: int = Field(foreign_key="game.id", description="ID of the game")
    player_id: int = Field(foreign_key="player.id", description="ID of the player")
    
    game: "Game" = Relationship(back_populates="scores")
    player: "Player" = Relationship(back_populates="scores")

    @validator("score")
    def validate_score(cls, v, values):
        """Validate that the score is valid for the given category."""
        category = values.get("category")
        if category and v not in possible_scores.get(category, []):
            raise ValueError(f"Invalid score for category {category}")
        return v
