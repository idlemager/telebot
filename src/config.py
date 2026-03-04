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
    X_PROFILE_URL = os.getenv("X_PROFILE_URL", "https://x.com/idlemage")
    PLAYWRIGHT_HEADLESS = os.getenv("PLAYWRIGHT_HEADLESS", "false").lower() in ("1", "true", "yes")
    X_POST_ENABLED = os.getenv("X_POST_ENABLED", "false").lower() in ("1", "true", "yes")
    AD_TEXT = os.getenv("AD_TEXT", "$MOLT 正在BSC上蜕壳起飞！AI代理Moltbook已经30k+代理狂欢，$MOLT直接跟涨2267%不是梦！ 下一个AI meme王者？ 合约还在，速度上车！ https://four.meme/token/0x3fa50edec5b1303a4e0ab386e7a275fd1fe64444?code=8HN64XSS65G6 🦞💨")
    AD_INTERVAL_SECONDS = int(os.getenv("AD_INTERVAL_SECONDS", "1800"))
    AD_ENABLED = os.getenv("AD_ENABLED", "true").lower() in ("1", "true", "yes")
    FUNDING_SYMBOLS = os.getenv("FUNDING_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT")
    FUNDING_RATE_THRESHOLD = float(os.getenv("FUNDING_RATE_THRESHOLD", "0.0003"))
    ALPHA_MONITOR_ENABLED = os.getenv("ALPHA_MONITOR_ENABLED", "true").lower() in ("1", "true", "yes")
    LARGE_TRANSFER_THRESHOLD_USD = float(os.getenv("LARGE_TRANSFER_THRESHOLD_USD", "100000"))
    AUTO_TRADE_ENABLED = os.getenv("AUTO_TRADE_ENABLED", "false").lower() in ("1", "true", "yes")
    MAX_TRADE_USD = float(os.getenv("MAX_TRADE_USD", "50"))
    TRADE_SYMBOLS = os.getenv("TRADE_SYMBOLS", "BTC/USDT,ETH/USDT,SOL/USDT")
    TRADE_HEAT_THRESHOLD = float(os.getenv("TRADE_HEAT_THRESHOLD", "60"))
    ONCHAIN_ENABLED = os.getenv("ONCHAIN_ENABLED", "false").lower() in ("1", "true", "yes")
    STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "10"))
    TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "15"))
    MISSIONS_ENABLED = os.getenv("MISSIONS_ENABLED", "true").lower() in ("1", "true", "yes")
    BINANCE_COOKIES = os.getenv("BINANCE_COOKIES", "")
    
    # AI Analysis Configuration
    AI_ANALYSIS_ENABLED = os.getenv("AI_ANALYSIS_ENABLED", "false").lower() in ("1", "true", "yes")
    AI_API_KEY = os.getenv("AI_API_KEY", "")
    AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
    AI_MODEL = os.getenv("AI_MODEL", "gpt-3.5-turbo")

    # Polymarket Configuration
    POLYMARKET_ENABLED = os.getenv("POLYMARKET_ENABLED", "true").lower() in ("1", "true", "yes")
    POLYMARKET_THRESHOLD = float(os.getenv("POLYMARKET_THRESHOLD", "0.90"))

    # Defaults
    DEFAULT_RISK_LEVEL = "medium"
    DEFAULT_TIMEFRAME = "15m"
    
    # Mock Data for testing if APIs are not available
    MOCK_MODE = False
