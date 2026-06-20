"""
Core Configuration Module
Đọc biến môi trường từ .env và cung cấp cho toàn bộ hệ thống.
"""
import os
from pathlib import Path
from dotenv import load_dotenv
from loguru import logger

# Tìm file .env ở thư mục gốc dự án
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)


class Config:
    """Cấu hình trung tâm - Tất cả module đọc config từ đây."""

    # --- Telegram ---
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # --- Binance ---
    BINANCE_API_KEY: str = os.getenv("BINANCE_API_KEY", "")
    BINANCE_API_SECRET: str = os.getenv("BINANCE_API_SECRET", "")

    # --- Database ---
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    REDIS_URL: str = os.getenv("REDIS_URL", "")

    # --- App Settings ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # --- Risk Management (hard caps tuyet doi, ap dung ca paper lan live) ---
    # Don vi: PCT la ty le tren balance; USD la gioi han tuyet doi. Cap nao chat hon thi thang.
    RISK_PER_TRADE: float = float(os.getenv("RISK_PER_TRADE", "0.02"))        # rui ro/lenh = 2% balance
    MAX_LEVERAGE: int = int(os.getenv("MAX_LEVERAGE", "10"))                  # hard cap leverage
    MAX_MARGIN_PER_TRADE_PCT: float = float(os.getenv("MAX_MARGIN_PER_TRADE_PCT", "0.10"))  # margin/lenh <= 10% balance
    MAX_MARGIN_PER_TRADE_USD: float = float(os.getenv("MAX_MARGIN_PER_TRADE_USD", "2000"))  # margin/lenh <= $2000
    MAX_TOTAL_MARGIN_PCT: float = float(os.getenv("MAX_TOTAL_MARGIN_PCT", "0.50"))          # tong margin mo <= 50% balance
    MAX_TOTAL_MARGIN_USD: float = float(os.getenv("MAX_TOTAL_MARGIN_USD", "8000"))          # tong margin mo <= $8000
    MAX_OPEN_POSITIONS: int = int(os.getenv("MAX_OPEN_POSITIONS", "8"))       # so lenh mo dong thoi toi da
    MAX_DAILY_LOSS_USD: float = float(os.getenv("MAX_DAILY_LOSS_USD", "1000"))  # lo toi da/ngay -> khoa mo lenh
    MAX_DAILY_LOSS_PCT: float = float(os.getenv("MAX_DAILY_LOSS_PCT", "0.10"))  # hoac 10% balance dau ngay

    @classmethod
    def validate(cls):
        """Kiểm tra các biến bắt buộc đã được điền chưa."""
        errors = []
        if not cls.TELEGRAM_BOT_TOKEN:
            errors.append("TELEGRAM_BOT_TOKEN chưa được cấu hình trong .env")
        if not cls.TELEGRAM_CHAT_ID:
            errors.append("TELEGRAM_CHAT_ID chưa được cấu hình trong .env")
        if errors:
            for e in errors:
                logger.warning(f"⚠️  {e}")
            return False
        logger.success("✅ Tất cả cấu hình hợp lệ!")
        return True


# Cấu hình Logging
logger.add(
    BASE_DIR / "logs" / "bot_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="7 days",
    level=Config.LOG_LEVEL,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {module}:{function}:{line} - {message}",
)
