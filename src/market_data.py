import ccxt
import pandas as pd
import numpy as np
import logging
from .config import Config
import httpx

logger = logging.getLogger(__name__)

class MarketDataEngine:
    def __init__(self):
        self.exchange = ccxt.binance()
        self.mock_mode = Config.MOCK_MODE

    def fetch_ohlcv(self, symbol, timeframe='15m', limit=100):
        if self.mock_mode:
            return self._generate_mock_data(limit)
        
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            logger.error(f"Error fetching OHLCV for {symbol}: {e}")
            return None

    def _generate_mock_data(self, limit):
        # Generate random price data for testing
        dates = pd.date_range(end=pd.Timestamp.now(), periods=limit, freq='15min')
        df = pd.DataFrame(index=dates)
        df['timestamp'] = dates
        df['open'] = np.random.uniform(100, 200, limit)
        df['high'] = df['open'] * np.random.uniform(1.0, 1.05, limit)
        df['low'] = df['open'] * np.random.uniform(0.95, 1.0, limit)
        df['close'] = np.random.uniform(df['low'], df['high'], limit)
        df['volume'] = np.random.uniform(1000, 50000, limit)
        return df

    def get_ticker(self, symbol):
        if self.mock_mode:
            return {
                'symbol': symbol,
                'last': 150.0,
                'percentage': 2.5,
                'quoteVolume': 1000000
            }
        try:
            return self.exchange.fetch_ticker(symbol)
        except Exception as e:
            logger.error(f"Error fetching ticker for {symbol}: {e}")
            return None

    def list_usdt_pairs(self, limit=100):
        if self.mock_mode:
            return ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'PEPE/USDT', 'WIF/USDT']
        try:
            markets = self.exchange.load_markets()
            symbols = [s for s, m in markets.items() if m.get('quote') == 'USDT' and m.get('active') != False]
            symbols.sort()
            return symbols[:limit]
        except Exception as e:
            logger.error(f"Error loading markets: {e}")
            return ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'PEPE/USDT', 'WIF/USDT']

    def fetch_current_funding_rate(self, symbol):
        if not symbol:
            return None
        try:
            base = symbol.upper().replace("/", "")
            url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={base}"
            with httpx.Client(timeout=8) as client:
                r = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code != 200:
                    return None
                data = r.json()
                v = data.get("lastFundingRate")
                if v is None:
                    return None
                return float(v)
        except Exception as e:
            logger.error(f"Error fetching funding rate for {symbol}: {e}")
            return None
