import sys
from pathlib import Path
from loguru import logger

# Configure logger
#
# 设计：
#   1. stdout sink：INFO 级，调用方方便实时看（如 streamlit run）
#   2. file sink：DEBUG 级，按 5 MB rotation，保留 5 个 backup
#      路径：data/logs/agent.log + .log.1 .log.2 ...
#   3. Windows GBK 问题：loguru 默认会带 colors，streamlit 重定向时可能乱码
#      → 用 ansi=False 避免 ANSI 控制字符
#
# 用法：
#   from src.shared.logger import logger
#   logger.debug("...")     # 进文件不进 stdout
#   logger.info("...")       # 进 stdout + 文件
#   logger.exception("...")  # 完整 traceback

_LOG_DIR = Path(__file__).resolve().parents[2] / "data" / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_AGENT_LOG = _LOG_DIR / "agent.log"

logger.remove()
logger.add(
    sys.stdout,
    level="INFO",
    colorize=False,
    format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <7}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | {message}",
)
logger.add(
    str(_AGENT_LOG),
    level="DEBUG",
    rotation="5 MB",
    retention=5,
    encoding="utf-8",
    enqueue=True,        # 异步写（不阻塞主线程）
    backtrace=True,
    diagnose=False,      # 不在生产里暴露本地变量
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <7} | {name}:{function}:{line} | {message}",
)
