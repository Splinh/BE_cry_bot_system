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
    TELEGRAM_GROUP_CHAT_ID: str = os.getenv("TELEGRAM_GROUP_CHAT_ID", "")

    # --- Zalo Bot ---
    ZALO_BOT_TOKEN: str = os.getenv("ZALO_BOT_TOKEN", "")
    ZALO_ADMIN_CHAT_ID: str = os.getenv("ZALO_ADMIN_CHAT_ID", "")
    ZALO_GROUP_CHAT_ID: str = os.getenv("ZALO_GROUP_CHAT_ID", "")

    # Để tương thích ngược nếu có phần code cũ tham chiếu:
    ZALO_ACCESS_TOKEN: str = os.getenv("ZALO_ACCESS_TOKEN", os.getenv("ZALO_BOT_TOKEN", ""))
    ZALO_USER_ID: str = os.getenv("ZALO_USER_ID", os.getenv("ZALO_ADMIN_CHAT_ID", ""))


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

    # --- Trailing Stop & Position Sizing (tuning) ---
    SL_PCT_FLOOR: float = float(os.getenv("SL_PCT_FLOOR", "0.015"))            # san SL% toi thieu khi tinh size
    CHANDELIER_ATR_MULTIPLIER: float = float(os.getenv("CHANDELIER_ATR_MULTIPLIER", "3.5"))  # he so ATR Chandelier trail
    ATR_FALLBACK_PCT: float = float(os.getenv("ATR_FALLBACK_PCT", "0.02"))     # ATR fallback = 2% gia entry

    # --- Trend Filter ---
    ENABLE_TREND_FILTER: bool = os.getenv("ENABLE_TREND_FILTER", "true").lower() == "true"

    # --- AI / LLM Chatbox (OmniRouter - self-hosted gateway) ---
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "omnirouter")                # omnirouter | (sau này: gemini, anthropic, local)
    OMNIROUTER_BASE_URL: str = os.getenv("OMNIROUTER_BASE_URL", "http://139.99.89.215:20128/v1")
    OMNIROUTER_API_KEY: str = os.getenv("OMNIROUTER_API_KEY", "")
    OMNIROUTER_MODEL: str = os.getenv("OMNIROUTER_MODEL", "auto/best-chat")
    LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "30"))                     # giây
    LLM_MAX_HISTORY: int = int(os.getenv("LLM_MAX_HISTORY", "8"))              # số lượt hội thoại nhớ / chat_id
    AI_RATE_LIMIT_PER_MIN: int = int(os.getenv("AI_RATE_LIMIT_PER_MIN", "5"))   # max câu hỏi / phút / user

    # --- ML Signal Intelligence ---
    ML_ENABLED: bool = os.getenv("ML_ENABLED", "true").lower() == "true"
    ML_MIN_TRADES: int = int(os.getenv("ML_MIN_TRADES", "30"))                  # trades tối thiểu để train
    ML_RETRAIN_INTERVAL: int = int(os.getenv("ML_RETRAIN_INTERVAL", "20"))      # retrain sau mỗi N trades mới

    # --- Whale & Smart Money Tracker ---
    WHALE_ENABLED: bool = os.getenv("WHALE_ENABLED", "true").lower() == "true"
    WHALE_SCAN_INTERVAL: int = int(os.getenv("WHALE_SCAN_INTERVAL", "300"))     # quét mỗi 5 phút
    WHALE_ALERT_API_KEY: str = os.getenv("WHALE_ALERT_API_KEY", "")             # free tier: 10 calls/min

    # --- News Intelligence ---
    NEWS_INTEL_ENABLED: bool = os.getenv("NEWS_INTEL_ENABLED", "true").lower() == "true"
    NEWS_LLM_FOR_HIGH_IMPACT: bool = os.getenv("NEWS_LLM_FOR_HIGH_IMPACT", "true").lower() == "true"



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
