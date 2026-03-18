import sys
from loguru import logger

# Configure logger
logger.remove()
logger.add(sys.stdout, level="INFO")
