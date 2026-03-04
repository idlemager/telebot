import logging
import ccxt
from .config import Config
from .market_data import MarketDataEngine

logger = logging.getLogger(__name__)

class TradingEngine:
    def __init__(self):
        self.enabled = bool(Config.AUTO_TRADE_ENABLED)
        self.max_usd = float(getattr(Config, "MAX_TRADE_USD", 50))
        self.heat_threshold = float(getattr(Config, "TRADE_HEAT_THRESHOLD", 60))
        self.exchange = ccxt.binance({
            'apiKey': Config.BINANCE_API_KEY or '',
            'secret': Config.BINANCE_API_SECRET or '',
            'enableRateLimit': True
        })
        self.market = MarketDataEngine()

    def _get_price(self, symbol):
        t = self.market.get_ticker(symbol)
        if not t:
            return None
        return t.get('last')

    def _get_balance(self, currency):
        try:
            bal = self.exchange.fetch_balance()
            info = bal.get(currency) or {}
            free = info.get('free')
            if free is None and isinstance(bal, dict):
                free = bal.get('free', {}).get(currency)
            return float(free or 0)
        except Exception as e:
            logger.error(f"Error fetching balance {currency}: {e}")
            return 0.0

    def buy_spot_usdt(self, symbol, usd_amount):
        if not self.enabled:
            return None
        try:
            price = self._get_price(symbol)
            if not price or price <= 0:
                return None
            base_amount = usd_amount / price
            base = symbol.split('/')[0]
            usdt_bal = self._get_balance('USDT')
            if usdt_bal < usd_amount:
                return None
            o = self.exchange.create_order(symbol, 'market', 'buy', self.exchange.amount_to_precision(symbol, base_amount))
            return o
        except Exception as e:
            logger.error(f"Buy spot error {symbol}: {e}")
            return None

    def sell_spot_all(self, symbol):
        if not self.enabled:
            return None
        try:
            base = symbol.split('/')[0]
            base_bal = self._get_balance(base)
            if base_bal <= 0:
                return None
            o = self.exchange.create_order(symbol, 'market', 'sell', self.exchange.amount_to_precision(symbol, base_bal))
            return o
        except Exception as e:
            logger.error(f"Sell spot error {symbol}: {e}")
            return None

    def act_on_signal(self, symbol, signal):
        if not self.enabled:
            return None
        try:
            heat = float(signal.get('heat_score') or 0)
            whale = signal.get('whale_data') or {}
            has_whale = bool(whale.get('has_activity'))
            dirn = str(signal.get('direction') or '')
            if has_whale and heat >= self.heat_threshold and dirn in ('bullish', 'neutral'):
                usd = min(self.max_usd, self._get_balance('USDT'))
                if usd >= 10:
                    return self.buy_spot_usdt(symbol, usd)
            if has_whale and dirn == 'bearish':
                return self.sell_spot_all(symbol)
            return None
        except Exception as e:
            logger.error(f"Act on signal error {symbol}: {e}")
            return None
