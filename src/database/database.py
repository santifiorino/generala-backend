import random
from datetime import datetime

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine, select

from src.config import settings
from src.database.models import Category, Game, GamePlayer, Player, Score
from src.logging_config import logger

# Create engine
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if settings.DB_TYPE == "sqlite" else {},
    echo=False
)

def create_default_players(session: Session):
    """Create default players if they don't exist"""
    # Define players with their win counts (adjusted for generala_servida counting as 2)
    players_with_wins = [
        {"name": "Tincho", "wins": 7},
        {"name": "Marcos", "wins": 4, "generala_servida_date": "2025-06-16"},  # 5 regular wins + 1 generala_servida (2 wins) = 7 total
        {"name": "Iván", "wins": 3},
        {"name": "Juli", "wins": 3},
        {"name": "Fiori", "wins": 3},
        {"name": "Matute", "wins": 3},
        {"name": "Luqui", "wins": 1, "generala_servida_date": "2025-04-17"},  # 2 regular wins + 1 generala_servida (2 wins) = 4 total
        {"name": "Juanma", "wins": 2},
        {"name": "Toto", "wins": 1},
        {"name": "Pato", "wins": 0},
    ]
    
    # Check if players already exist
    existing_players = session.exec(select(Player)).all()
    
    if not existing_players:
        # Create players first
        created_players = {}
        for player_data in players_with_wins:
            player = Player(name=player_data["name"])
            session.add(player)
            session.flush()  # Flush to get the ID
            created_players[player.name] = player
        
        session.commit()
        
        # Create historical games to establish win counts
        base_date = datetime.now()
        ivans_games = []  # Track Iván's games to add score later
        
        # Get a list of all player IDs to choose from
        all_player_ids = [p.id for p in created_players.values()]
        
        for player_data in players_with_wins:
            player_name = player_data["name"]
            wins_needed = player_data["wins"]
            player = created_players[player_name]
            
            # Check if this player has a generala_servida game
            generala_servida_date = player_data.get("generala_servida_date")
            
            # Create regular games where this player wins
            for _ in range(wins_needed):
                # Create a game
                game = Game(
                    winner_id=player.id,
                    created_at=base_date,
                    generala_servida=False
                )
                session.add(game)
                session.flush()
                
                # Add the winner as a player
                game_player = GamePlayer(
                    game_id=game.id,
                    player_id=player.id
                )
                session.add(game_player)
                
                # Add 4 other random players for it to count in the ranking
                other_players = [pid for pid in all_player_ids if pid != player.id]
                random_players = random.sample(other_players, 4)
                
                for player_id in random_players:
                    game_player = GamePlayer(
                        game_id=game.id,
                        player_id=player_id
                    )
                    session.add(game_player)
                
                # Track Iván's games for score creation
                if player_name == "Iván":
                    ivans_games.append(game)
            
            # Create generala_servida game if specified
            if generala_servida_date:
                # Parse the date
                generala_date = datetime.strptime(generala_servida_date, "%Y-%m-%d")
                
                game = Game(
                    winner_id=player.id,
                    created_at=generala_date,
                    generala_servida=True
                )
                session.add(game)
                session.flush()
                
                # Add the winner as a player
                game_player = GamePlayer(
                    game_id=game.id,
                    player_id=player.id
                )
                session.add(game_player)
                
                # Add 4 other random players for it to count in the ranking
                other_players = [pid for pid in all_player_ids if pid != player.id]
                random_players = random.sample(other_players, 4)
                
                for player_id in random_players:
                    game_player = GamePlayer(
                        game_id=game.id,
                        player_id=player_id
                    )
                    session.add(game_player)
        
        # Add score of 214 to Iván's first game in category "1"
        if ivans_games:
            ivans_first_game = ivans_games[0]
            score = Score(
                game_id=ivans_first_game.id,
                player_id=created_players["Iván"].id,
                category=Category.ONE,
                score=214
            )
            session.add(score)
        
        session.commit()
        logger.info(f"Created {len(players_with_wins)} default players with their win counts!")
    else:
        logger.info(f"Database already has {len(existing_players)} players.")

def _run_migrations():
    """Add columns and adjust constraints that may be missing from older schemas."""
    inspector = inspect(engine)
    migrations = [
        ("player", "is_guest", "ALTER TABLE player ADD COLUMN is_guest BOOLEAN DEFAULT FALSE"),
        ("gameplayer", "is_guest", "ALTER TABLE gameplayer ADD COLUMN is_guest BOOLEAN DEFAULT FALSE"),
    ]
    with engine.begin() as conn:
        for table, column, ddl in migrations:
            if table in inspector.get_table_names():
                cols = [c["name"] for c in inspector.get_columns(table)]
                if column not in cols:
                    conn.execute(text(ddl))
                    logger.info(f"Migration: added {column} to {table}")

        # Drop the unique constraint on player.name so guests can share names
        if "player" in inspector.get_table_names():
            unique_constraints = inspector.get_unique_constraints("player")
            for uc in unique_constraints:
                if "name" in uc.get("column_names", []):
                    try:
                        if settings.DB_TYPE == "sqlite":
                            conn.execute(text(f"DROP INDEX IF EXISTS \"{uc['name']}\""))
                        else:
                            conn.execute(text(f"ALTER TABLE player DROP CONSTRAINT \"{uc['name']}\""))
                        logger.info(f"Migration: dropped unique constraint {uc['name']} on player.name")
                    except Exception:
                        logger.warning("Could not drop unique constraint on player.name; may need manual fix")

def create_db_and_tables():
    """Create database and tables."""
    SQLModel.metadata.create_all(engine)
    _run_migrations()
    logger.info("Database and tables created or verified successfully!")
    
    with Session(engine) as session:
        # Check if players already exist before trying to create them
        existing_players = session.exec(select(Player)).all()
        if not existing_players:
            create_default_players(session)
        else:
            logger.info("Default players already exist, skipping creation.")

def get_session():
    """Dependency to get database session"""
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception as e:
        logger.error(f"Session rollback due to exception: {e}", exc_info=True)
        session.rollback()
        raise
    finally:
        session.close() 
