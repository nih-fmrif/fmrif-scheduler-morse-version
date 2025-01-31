import logging
from pathlib import Path
import dotenv
import os
logger = logging.getLogger(__name__)

def find_envfile():
    env_file = dotenv.find_dotenv()
    if not env_file:
        raise ValueError("Failed to find .env")

    env_file = Path(env_file).resolve()
    logger.info(f"Setting environment variables from {env_file} (with override=True)")
    project_root = Path(__file__).resolve().parent.parent

    # Check if .env is outside the project root or its parent
    if not env_file.is_relative_to(project_root):
        logger.warning(f".env file found outside project directory tree: {env_file}")
    return env_file

def find_and_load_env():
    """Find and load the .env file with detailed logging"""
    # Get absolute path to project root (parent of scheduler directory)
    project_root = Path(__file__).resolve().parent.parent
    logger.info(f"Project root directory: {project_root}")
    
    # Check for .env file
    env_file = project_root / '.env'
    env_sample = project_root / '.env.sample'
    
    logger.info(f"Checking for .env at: {env_file}")
    if env_file.exists():
        logger.info(f"Found .env file at {env_file}")
        dotenv.load_dotenv(env_file, override=True)
        logger.info("Loaded .env file")
        # Log some environment variables to verify they were loaded
        for key in ['SCHEDULER_SECRET_KEY', 'POSTGRES_USER', 'LDAP_HOST']:
            value = os.getenv(key)
            if value:
                logger.info(f"Loaded {key}={value[:3]}***") # Only show first 3 chars for security
            else:
                logger.warning(f"Environment variable {key} not found")
        return str(env_file)
    elif env_sample.exists():
        logger.warning(f".env not found, using .env.sample from {env_sample}")
        dotenv.load_dotenv(env_sample, override=True)
        return str(env_sample)
    else:
        logger.error("No .env or .env.sample file found!")
        return None