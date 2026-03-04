import requests
import json
import logging
from .config import Config
from .database import Database

logger = logging.getLogger(__name__)

class PolymarketWatcher:
    def __init__(self):
        self.enabled = Config.POLYMARKET_ENABLED
        self.threshold = Config.POLYMARKET_THRESHOLD
        self.api_url = "https://gamma-api.polymarket.com/events"
        self.db = Database()

    def check_market_movements(self):
        """
        Fetches Polymarket events and checks for high probability outcomes.
        Returns a list of alerts for new high probability events.
        """
        if not self.enabled:
            return []

        try:
            params = {
                "limit": 50,
                "active": "true",
                "closed": "false",
                "tag_slug": "crypto",
                # "volume_min": 1000, # Removed as it might cause 422 on /events
                "order": "volume", # Try simple 'volume' or remove if fails
                "ascending": "false"
            }
            
            response = requests.get(self.api_url, params=params, timeout=10)
            response.raise_for_status()
            events = response.json()
            
            alerts = []
            
            for event in events:
                event_title = event.get('title')
                event_slug = event.get('slug')
                markets = event.get('markets', [])
                
                for market in markets:
                    market_id = market.get('id')
                    question = market.get('question')
                    outcomes = market.get('outcomes')
                    outcome_prices = market.get('outcomePrices')
                    
                    if not outcomes or not outcome_prices:
                        continue
                        
                    # Parse prices if they are strings/JSON
                    if isinstance(outcome_prices, str):
                        try:
                            outcome_prices = json.loads(outcome_prices)
                        except:
                            continue
                    
                    if isinstance(outcomes, str):
                        try:
                            outcomes = json.loads(outcomes)
                        except:
                            continue
                            
                    # Check each outcome
                    for i, price_str in enumerate(outcome_prices):
                        try:
                            price = float(price_str)
                            # We only care if it's high probability (> 90%)
                            # But we also want to avoid reporting "1.0" or "0.0" if it's basically resolved/boring,
                            # unless it just became resolved.
                            # For now, let's report anything > threshold.
                            
                            if price > self.threshold:
                                outcome_label = outcomes[i]
                                
                                # Unique ID for this specific alert
                                # We use a combination of market ID and outcome
                                # To avoid re-alerting, we store this in DB.
                                # However, if the price drops and goes back up, we might want to alert again?
                                # For now, let's assume "Once it hits 90%, we alert once".
                                # If we want to support re-alerts, we would need a more complex state tracking (e.g. timestamp).
                                # But reusing 'processed_news' table is easiest.
                                
                                alert_id = f"poly_{market_id}_{outcome_label}_90"
                                
                                if self.db.claim_news_if_new(alert_id, "Polymarket"):
                                    # It's new!
                                    alerts.append({
                                        'type': 'polymarket_high_prob',
                                        'event_title': event_title,
                                        'question': question,
                                        'outcome': outcome_label,
                                        'price': price,
                                        'link': f"https://polymarket.com/event/{event_slug}",
                                        'market_slug': market.get('slug')
                                    })
                                    logger.info(f"Polymarket Alert: {question} -> {outcome_label} ({price*100:.1f}%)")
                                    
                        except ValueError:
                            continue
                            
            return alerts
            
        except Exception as e:
            logger.error(f"Error checking Polymarket: {e}")
            return []
