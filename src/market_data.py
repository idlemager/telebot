import ccxt
import pandas as pd
import logging
import httpx

logger = logging.getLogger(__name__)

class MarketDataEngine:
    def __init__(self):
        self.exchange = ccxt.binance()

    def fetch_ohlcv(self, symbol, timeframe='15m', limit=100):
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            logger.error(f"Error fetching OHLCV for {symbol}: {e}")
            return None

    def get_ticker(self, symbol):
        try:
            return self.exchange.fetch_ticker(symbol)
        except Exception as e:
            logger.error(f"Error fetching ticker for {symbol}: {e}")
            return None

    def list_usdt_pairs(self, limit=100):
        try:
            markets = self.exchange.load_markets()
            symbols = [
                s for s, m in markets.items()
                if m.get('quote') == 'USDT'
                and m.get('active') != False
                and m.get('spot') is True
                and ":" not in s
            ]
            symbols.sort()
            return symbols[:limit]
        except Exception as e:
            logger.error(f"Error loading markets: {e}")
            return []

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

    def list_futures_usdt_pairs(self, limit=1000):
        try:
            url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
            with httpx.Client(timeout=10) as client:
                r = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code != 200:
                    return []
                data = r.json()
            symbols = []
            for item in data.get("symbols", []):
                if item.get("quoteAsset") != "USDT":
                    continue
                if item.get("contractType") != "PERPETUAL":
                    continue
                if item.get("status") != "TRADING":
                    continue
                sym = item.get("symbol")
                if not sym:
                    continue
                symbols.append(sym.upper())
            symbols.sort()
            return symbols[:limit]
        except Exception as e:
            logger.error(f"Error loading futures markets: {e}")
            return []

    def fetch_all_funding_rates(self):
        try:
            url = "https://fapi.binance.com/fapi/v1/premiumIndex"
            with httpx.Client(timeout=10) as client:
                r = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code != 200:
                    return {}
                data = r.json()
            rates = {}
            if isinstance(data, dict):
                sym = data.get("symbol")
                val = data.get("lastFundingRate")
                if sym and val is not None:
                    rates[str(sym).upper()] = float(val)
                return rates
            for row in data or []:
                sym = row.get("symbol")
                val = row.get("lastFundingRate")
                if not sym or val is None:
                    continue
                rates[str(sym).upper()] = float(val)
            return rates
        except Exception as e:
            logger.error(f"Error fetching all funding rates: {e}")
            return {}

    def fetch_futures_24h_quote_volumes(self):
        try:
            url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
            with httpx.Client(timeout=10) as client:
                r = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code != 200:
                    return {}
                data = r.json()
            volumes = {}
            rows = data if isinstance(data, list) else [data]
            for row in rows:
                sym = row.get("symbol")
                v = row.get("quoteVolume")
                if not sym or v is None:
                    continue
                try:
                    volumes[str(sym).upper()] = float(v)
                except Exception:
                    continue
            return volumes
        except Exception as e:
            logger.error(f"Error fetching futures 24h quote volumes: {e}")
            return {}
