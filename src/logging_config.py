import logging
import sys
from logging.handlers import TimedRotatingFileHandler


def setup_logging():
    """Set up logging configuration."""
    
    # Create logger
    logger = logging.getLogger("generala")
    logger.setLevel(logging.INFO)
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create console handler and set level to INFO
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    
    # Create file handler and set level to WARNING
    file_handler = TimedRotatingFileHandler(
        "logs/generala.log", when="midnight", interval=1, backupCount=7
    )
    file_handler.setLevel(logging.WARNING)
    file_handler.setFormatter(formatter)
    
    # Add handlers to the logger
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger

# Create logs directory if it doesn't exist
import os

if not os.path.exists("logs"):
    os.makedirs("logs")

logger = setup_logging() 
