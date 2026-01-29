import logging
from .market_data import MarketDataEngine
from .news_scanner import NewsScanner
from .whale_watcher import WhaleWatcher
from .config import Config

logger = logging.getLogger(__name__)

class SignalEngine:
    def __init__(self):
        self.market = MarketDataEngine()
        self.news = NewsScanner()
        self.whale = WhaleWatcher()

    def analyze_symbol(self, symbol):
        # 1. Get Market Data
        df = self.market.fetch_ohlcv(symbol)
        if df is None or df.empty:
            return None
            
        # 2. Market Anomaly Detection
        # Check volume spike (latest volume vs moving average)
        avg_volume = df['volume'].rolling(window=20).mean().iloc[-1]
        current_volume = df['volume'].iloc[-1]
        volume_score = (current_volume / avg_volume) * 100 if avg_volume > 0 else 0
        
        # 3. News Analysis
        news_data = self.news.scan_news(symbol)
        
        # 4. Whale Analysis
        whale_data = self.whale.scan_whale_activity(symbol)
        try:
            threshold = Config.WHALE_THRESHOLD_USD
            if not whale_data or not whale_data.get('has_activity'):
                pass
            else:
                flow = abs(whale_data.get('net_flow', 0))
                if flow < threshold:
                    whale_data = {
                        'has_activity': False,
                        'net_flow': 0,
                        'whale_count': 0,
                        'top_source': whale_data.get('top_source'),
                        'summary': "暂无显著鲸鱼异动",
                        'sentiment': whale_data.get('sentiment', 'neutral'),
                        'details': ""
                    }
        except Exception:
            pass
        
        # 5. Risk Analysis (Simplified)
        risk_level = self._calculate_risk(df)
        
        # 6. Signal Generation Logic
        
        signal = {
            'symbol': symbol,
            'price': df['close'].iloc[-1],
            'direction': news_data['sentiment'], # Simplified
            'heat_score': news_data['heat_score'],
            'volume_score': round(volume_score, 2),
            'narrative': news_data['narrative'],
            'risk_level': risk_level,
            'news_data': news_data,
            'whale_data': whale_data
        }
        
        return signal

    def _calculate_risk(self, df):
        # Simple volatility based risk
        volatility = df['close'].pct_change().std()
        if volatility > 0.05: # High volatility
            return 'High'
        elif volatility > 0.02:
            return 'Medium'
        else:
            return 'Low'

    def scan_market(self, symbols):
        signals = []
        for symbol in symbols:
            sig = self.analyze_symbol(symbol)
            if sig:
                # Filter logic
                if sig['heat_score'] > 50 or sig['volume_score'] > 150: # Thresholds
                    signals.append(sig)
        return signals
