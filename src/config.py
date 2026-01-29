import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
    BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
    DB_PATH = os.getenv("DB_PATH", "trendpulse.db")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    WHALE_THRESHOLD_USD = int(os.getenv("WHALE_THRESHOLD_USD", "10000000"))
    TWITTER_REAL_MODE = os.getenv("TWITTER_REAL_MODE", "false").lower() in ("1", "true", "yes")
    LOG_MAX_LEN = int(os.getenv("LOG_MAX_LEN", "1000"))
    
    # Defaults
    DEFAULT_RISK_LEVEL = "medium"
    DEFAULT_TIMEFRAME = "15m"
    
    # Mock Data for testing if APIs are not available
    MOCK_MODE = False
