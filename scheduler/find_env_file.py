import logging
from pathlib import Path

import dotenv

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
