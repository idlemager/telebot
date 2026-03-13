import logging
import feedparser
from datetime import datetime
import time
import os
import json
import httpx
from bs4 import BeautifulSoup
import re
from .config import Config
from .ai_analyzer import AIAnalyzer
from .market_data import MarketDataEngine
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

class NewsScanner:
    def __init__(self):
        self.narratives = ['AI', 'Meme', 'L2', 'DeFi', 'GameFi', 'RWA']
        self.ai_analyzer = AIAnalyzer()
        self.market = MarketDataEngine()
        self.symbol_heat = {}
        self.source_weights = {
            'Binance公告': 1.6,
            'OKX公告': 1.5,
            'HTX公告': 1.4,
            'Gate公告': 1.4,
            'Coinbase': 1.3,
            'BlockBeats': 1.2,
            'PANews': 1.2,
            'InvestingCN': 1.1,
            'Twitter': 1.0
        }
        self.event_rules = [
            {'kind': 'bearish', 'label': '下架/停止交易', 'weight': 42, 'patterns': [r'\bdelist(?:ing)?\b', r'下架', r'停止交易', r'trading\s+suspension', r'暂停交易']},
            {'kind': 'bearish', 'label': '安全事件', 'weight': 34, 'patterns': [r'\bhack(?:ed|ing)?\b', r'exploit', r'安全事件', r'被盗', r'漏洞']},
            {'kind': 'bearish', 'label': '监管/诉讼风险', 'weight': 26, 'patterns': [r'\blawsuit\b', r'\binvestigation\b', r'监管', r'调查', r'诉讼']},
            {'kind': 'bearish', 'label': '解锁/抛压', 'weight': 20, 'patterns': [r'\bunlock(?:ed)?\b', r'token\s+unlock', r'解锁', r'大额解锁', r'抛压']},
            {'kind': 'bullish', 'label': '交易所上币', 'weight': 30, 'patterns': [r'\blisting\b', r'上线', r'上币', r'launchpool', r'launchpad']},
            {'kind': 'bullish', 'label': '合作/采用', 'weight': 16, 'patterns': [r'partnership', r'合作', r'采用', r'integration', r'集成']},
            {'kind': 'bullish', 'label': 'ETF/重大通过', 'weight': 24, 'patterns': [r'\betf\b', r'批准', r'通过', r'approval']}
        ]
        self.rss_sources = {
            'BlockBeats': "https://api.theblockbeats.news/v2/rss/newsflash",
            'PANews': "https://www.panewslab.com/zh/rss/newsflash.xml",
            'InvestingCN': "https://cn.investing.com/rss/news_301.rss",
            'Binance公告': [
                "https://rsshub.app/binance/announcement/zh-CN",
                "https://rsshub.app/binance/announcement",
                "https://rsshub.rssforever.com/binance/announcement/zh-CN",
                "https://rsshub.rssforever.com/binance/announcement"
            ],
            'OKX公告': [
                "https://rsshub.app/okx/announcement/zh-CN",
                "https://rsshub.rssforever.com/okx/announcement/zh-CN"
            ],
            'HTX公告': [
                "https://rsshub.app/huobi/announcement/zh-CN",
                "https://rsshub.rssforever.com/huobi/announcement/zh-CN"
            ],
            'Coinbase': [
                "https://rsshub.app/coinbase/blog", 
                "https://rsshub.rssforever.com/coinbase/blog"
            ],
            'Gate公告': [
                "https://rsshub.app/gate/announcement/zh-CN",
                "https://rsshub.rssforever.com/gate/announcement/zh-CN"
            ]
        }
        self.twitter_real_mode = Config.TWITTER_REAL_MODE
        self.twitter_sources = self._load_twitter_sources() if self.twitter_real_mode else []
        self.kol_handles = self._extract_kol_handles(self.twitter_sources) if self.twitter_real_mode else []
        self.last_published = {} # {source_name: last_link}
        
    def _load_twitter_sources(self):
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            file_path = os.path.join(current_dir, 'data', 'smart_money_list.json')
            
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    sources = [{'name': item['name'], 'url': item['twitter']} for item in data]
                    logger.info(f"Loaded {len(sources)} twitter sources.")
                    return sources
            return []
        except Exception as e:
            logger.error(f"Error loading twitter sources: {e}")
            return []
        
    def _extract_kol_handles(self, sources):
        handles = []
        for s in sources:
            url = (s.get('url') or '').strip()
            h = None
            m = re.search(r"(?:twitter\.com|x\.com)/([A-Za-z0-9_]+)", url)
            if m:
                h = m.group(1)
            if h:
                handles.append({'name': s.get('name') or h, 'handle': h})
        return handles

    def _get_valid_symbols(self):
        if not hasattr(self, '_valid_symbols'):
            try:
                pairs = self.market.list_usdt_pairs()
                self._valid_symbols = set(p.split('/')[0] for p in pairs)
            except:
                self._valid_symbols = set(['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'DOGE', 'ADA', 'AVAX', 'LINK', 'DOT'])
        return self._valid_symbols

    def _extract_symbols(self, text):
        if not text:
            return []
        text_upper = text.upper()
        found = set()
        matches = re.findall(r'\$([A-Z]{2,6})', text_upper)
        for m in matches:
            found.add(m)
        valid = self._get_valid_symbols()
        words = re.findall(r'\b[A-Z]{2,6}\b', text_upper)
        for w in words:
            if w in valid and w not in ['GAS', 'FUN', 'ONE', 'SUN', 'BID', 'BET']:
                found.add(w)
        return sorted(found)

    def _detect_event_signal(self, text):
        if not text:
            return {'net_score': 0, 'bullish_hits': 0, 'bearish_hits': 0, 'alerts': []}
        net_score = 0
        bullish_hits = 0
        bearish_hits = 0
        alerts = []
        for rule in self.event_rules:
            matched = False
            for pat in rule['patterns']:
                if re.search(pat, text, flags=re.IGNORECASE):
                    matched = True
                    break
            if not matched:
                continue
            if rule['kind'] == 'bullish':
                net_score += rule['weight']
                bullish_hits += 1
                alerts.append(f"利好:{rule['label']}")
            else:
                net_score -= rule['weight']
                bearish_hits += 1
                alerts.append(f"利空:{rule['label']}")
        return {
            'net_score': net_score,
            'bullish_hits': bullish_hits,
            'bearish_hits': bearish_hits,
            'alerts': alerts[:4]
        }

    def analyze_article_event(self, article):
        text = f"{article.get('title', '')} {article.get('summary', '')}"
        signal = self._detect_event_signal(text)
        symbols = self._extract_symbols(text)
        return {
            'net_score': signal.get('net_score', 0),
            'bullish_hits': signal.get('bullish_hits', 0),
            'bearish_hits': signal.get('bearish_hits', 0),
            'alerts': signal.get('alerts', []),
            'symbols': symbols
        }

    def _update_symbol_heat(self, text, source_name='News'):
        try:
            found = self._extract_symbols(text)
            source_weight = self.source_weights.get(source_name, 1.0)
            event_signal = self._detect_event_signal(text)
            for symbol in found:
                self._add_heat(symbol, source_weight, event_signal)
        except Exception as e:
            logger.error(f"Error updating symbol heat: {e}")

    def _add_heat(self, symbol, weight, event_signal):
        now = time.time()
        if symbol not in self.symbol_heat:
            self.symbol_heat[symbol] = {
                'score': 0,
                'last_updated': now,
                'mentions': 0,
                'bullish_events': 0,
                'bearish_events': 0,
                'alerts': []
            }
        
        entry = self.symbol_heat[symbol]
        hours_passed = (now - entry['last_updated']) / 3600
        decay = hours_passed * 5
        entry['score'] = max(0, entry['score'] - decay)
        base_boost = 8 * weight
        event_boost = min(30, abs(event_signal.get('net_score', 0)) * 0.45)
        entry['score'] = min(100, entry['score'] + base_boost + event_boost)
        entry['mentions'] += 1
        entry['bullish_events'] += event_signal.get('bullish_hits', 0)
        entry['bearish_events'] += event_signal.get('bearish_hits', 0)
        if event_signal.get('alerts'):
            merged = (event_signal['alerts'] + entry.get('alerts', []))
            dedup = []
            for it in merged:
                if it not in dedup:
                    dedup.append(it)
            entry['alerts'] = dedup[:6]
        entry['last_updated'] = now

    def scan_news(self, symbol):
        """
        Returns REAL heat score based on news mentions and market validation.
        NO SIMULATION.
        """
        base_symbol = symbol.split('/')[0] if '/' in symbol else symbol
        base_symbol = base_symbol.replace('USDT', '')
        
        # 1. Get Base Heat from Memory
        heat_data = self.symbol_heat.get(base_symbol)
        
        # If no data in memory, try a quick search
        if not heat_data:
            try:
                recent_news = self.search_symbol_news(symbol)
                if recent_news:
                    score = 0
                    for n in recent_news:
                        try:
                            score += 10
                        except:
                            pass
                    alerts = []
                    bullish_events = 0
                    bearish_events = 0
                    for news in recent_news:
                        signal = self._detect_event_signal(f"{news.get('title', '')} {news.get('summary', '')}")
                        bullish_events += signal.get('bullish_hits', 0)
                        bearish_events += signal.get('bearish_hits', 0)
                        alerts.extend(signal.get('alerts', []))
                    dedup_alerts = []
                    for alert in alerts:
                        if alert not in dedup_alerts:
                            dedup_alerts.append(alert)
                    self.symbol_heat[base_symbol] = {
                        'score': min(score, 80),
                        'last_updated': time.time(),
                        'mentions': len(recent_news),
                        'bullish_events': bullish_events,
                        'bearish_events': bearish_events,
                        'alerts': dedup_alerts[:6]
                    }
                    heat_data = self.symbol_heat[base_symbol]
                else:
                    self.symbol_heat[base_symbol] = {
                        'score': 0,
                        'last_updated': time.time(),
                        'mentions': 0,
                        'bullish_events': 0,
                        'bearish_events': 0,
                        'alerts': []
                    }
                    heat_data = self.symbol_heat[base_symbol]
            except Exception as e:
                logger.error(f"Error searching news for {symbol}: {e}")

        raw_score = heat_data['score'] if heat_data else 0
        mentions = heat_data['mentions'] if heat_data else 0
        bullish_events = heat_data.get('bullish_events', 0) if heat_data else 0
        bearish_events = heat_data.get('bearish_events', 0) if heat_data else 0
        event_alerts = (heat_data.get('alerts') or []) if heat_data else []
        validated_score = raw_score
        validation_msg = []
        if bearish_events > bullish_events:
            sentiment = 'bearish'
        elif bullish_events > bearish_events:
            sentiment = 'bullish'
        else:
            sentiment = 'neutral'
        if event_alerts:
            validation_msg.append("事件信号:" + "、".join(event_alerts[:3]))
        
        try:
            ticker = self.market.get_ticker(symbol)
            if ticker:
                pct_change = float(ticker.get('percentage', 0) or 0)
                df = self.market.fetch_ohlcv(symbol, limit=20)
                if df is not None and not df.empty:
                    recent_vol = df['volume'].iloc[-4:].mean()
                    avg_vol = df['volume'].iloc[:-4].mean()
                    vol_ratio = (recent_vol / avg_vol) if avg_vol > 0 else 1.0
                    if vol_ratio > 3.0:
                        validated_score += 30
                        validation_msg.append(f"量能爆发({vol_ratio:.1f}x)")
                    elif vol_ratio > 1.5:
                        validated_score += 10
                        validation_msg.append(f"量能放大({vol_ratio:.1f}x)")
                    elif vol_ratio < 0.5 and raw_score > 40:
                        validated_score *= 0.6
                        validation_msg.append("量能不足(未验证)")
                if pct_change > 10.0:
                    validated_score += 20
                    sentiment = 'bullish'
                    validation_msg.append(f"强势上涨(+{pct_change:.1f}%)")
                elif pct_change < -10.0:
                    sentiment = 'bearish'
                    validation_msg.append(f"强势下跌({pct_change:.1f}%)")
                elif abs(pct_change) < 1.0 and raw_score > 60:
                    validated_score *= 0.8
                    validation_msg.append("价格停滞")
                    
        except Exception as e:
            logger.error(f"Error validating market data for {symbol}: {e}")
            validation_msg.append("市场数据不可用")

        final_score = min(100, max(0, validated_score))
        
        narrative = "Quiet"
        if bearish_events >= 2 and bearish_events > bullish_events:
            narrative = "RiskOff"
        elif final_score > 80:
            narrative = "Hype/Trending"
        elif final_score > 50:
            narrative = "Active"
        
        return {
            'heat_score': round(final_score, 2),
            'sentiment': sentiment,
            'narrative': narrative,
            'mentions_growth': 0, 
            'kol_mentions': mentions,
            'extra_info': " | ".join(validation_msg),
            'bearish_events': bearish_events,
            'bullish_events': bullish_events,
            'alerts': event_alerts
        }

    def fetch_latest_news(self):
        """
        Fetches the latest news from all configured RSS sources.
        Returns a list of new articles since the last check.
        """
        all_new_articles = []
        
        for source_name, rss_url in self.rss_sources.items():
            try:
                candidates = rss_url if isinstance(rss_url, (list, tuple)) else [rss_url]
                feed = None
                entries = []
                last_used = None
                for cand in candidates:
                    logger.info(f"Fetching RSS from {source_name} ({cand})...")
                    f = feedparser.parse(cand)
                    if getattr(f, "entries", None):
                        feed = f
                        entries = f.entries
                        last_used = cand
                        break
                if not entries:
                    if source_name == 'Binance公告':
                        try:
                            page_articles = self._fetch_binance_announcements_page(limit=20)
                            if page_articles:
                                last_key = 'Binance公告_page'
                                last_pub = self.last_published.get(last_key)
                                new_page_articles = []
                                for a in page_articles:
                                    if a['link'] == last_pub:
                                        break
                                    new_page_articles.append(a)
                                if new_page_articles:
                                    self.last_published[last_key] = new_page_articles[0]['link']
                                    all_new_articles.extend(new_page_articles)
                            else:
                                logger.warning("No entries found in Binance公告 page fallback.")
                        except Exception as e:
                            logger.error(f"Error fetching Binance公告 page: {e}")
                        continue
                    logger.warning(f"No entries found in {source_name} RSS feed.")
                    continue

                new_articles = []
                last_pub = self.last_published.get(source_name)
                
                # If it's the first run for this source
                if last_pub is None:
                    if entries:
                        self.last_published[source_name] = entries[0].link
                        logger.info(f"Initialized {source_name} scanner. Latest: {entries[0].title}")
                    continue

                for entry in entries:
                    if entry.link == last_pub:
                        break
                    
                    # Basic info extraction
                    article = {
                        'source': source_name,
                        'title': entry.title,
                        'link': entry.link,
                        'summary': entry.summary if 'summary' in entry else '',
                        'published': entry.published if 'published' in entry else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    new_articles.append(article)

                # Update last_published if we found new articles
                if new_articles:
                    self.last_published[source_name] = new_articles[0]['link']
                    all_new_articles.extend(new_articles)
                
            except Exception as e:
                logger.error(f"Error fetching {source_name} RSS feed: {e}")
        
        try:
            page_articles = self._fetch_panews_newsflash_page()
            if page_articles:
                last_key = 'PANews_newsflash'
                last_pub = self.last_published.get(last_key)
                new_page_articles = []
                for a in page_articles:
                    if a['link'] == last_pub:
                        break
                    new_page_articles.append(a)
                if new_page_articles:
                    self.last_published[last_key] = new_page_articles[0]['link']
                    all_new_articles.extend(new_page_articles)
        except Exception as e:
            logger.error(f"Error fetching PANews newsflash page: {e}")
        
        if self.twitter_real_mode and self.kol_handles:
            try:
                for kol in self.kol_handles[:10]:
                    key = f"Twitter:{kol['handle']}"
                    try:
                        feed = feedparser.parse(f"https://nitter.net/{kol['handle']}/rss")
                    except Exception:
                        feed = None
                    if not feed or not getattr(feed, "entries", None):
                        continue
                    last_pub = self.last_published.get(key)
                    new_tweets = []
                    for entry in feed.entries:
                        link = getattr(entry, "link", "")
                        if not link:
                            continue
                        if last_pub and link == last_pub:
                            break
                        title = getattr(entry, "title", "")
                        summary = getattr(entry, "summary", "")
                        new_tweets.append({
                            'source': 'Twitter',
                            'author': kol['name'],
                            'title': title,
                            'link': link,
                            'summary': summary,
                            'published': getattr(entry, "published", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                        })
                    if new_tweets:
                        self.last_published[key] = new_tweets[0]['link']
                        all_new_articles.extend(new_tweets)
            except Exception as e:
                logger.error(f"Error fetching Twitter RSS: {e}")
        
        # Update Heat Map with ALL new articles
        if all_new_articles:
            logger.info(f"Updating symbol heat map with {len(all_new_articles)} new articles...")
            for article in all_new_articles:
                text = f"{article.get('title', '')} {article.get('summary', '')}"
                self._update_symbol_heat(text, source_name=article.get('source', 'News'))

        # AI Analysis and Filtering
        if self.ai_analyzer.enabled:
            filtered_articles = []
            logger.info(f"Analyzing {len(all_new_articles)} new articles with AI...")
            for article in all_new_articles:
                try:
                    # Skip analysis for tweets if needed, but let's analyze everything for now
                    analysis = self.ai_analyzer.analyze_news(article['title'], article['summary'])
                    article['ai_analysis'] = analysis
                    
                    # Filter logic: Keep High Impact OR Listing/Delisting OR High Score
                    if (analysis['impact'] == 'High' or 
                        analysis['type'] in ['Listing', 'Delisting'] or 
                        analysis.get('score', 0) >= 80):
                        filtered_articles.append(article)
                    else:
                        logger.info(f"Filtered out low impact news: {article['title']} (Impact: {analysis['impact']}, Type: {analysis['type']})")
                except Exception as e:
                    logger.error(f"Error during AI analysis for {article['title']}: {e}")
                    # Keep raw article if analysis fails to avoid missing potential alpha due to errors
                    filtered_articles.append(article)
            return filtered_articles
                
        return all_new_articles

    def search_symbol_news(self, symbol):
        results = []
        base = symbol.split('/')[0] if '/' in symbol else symbol
        base = base.replace('USDT', '')
        # Use regex for word boundary matching to avoid false positives (e.g. ETH in method)
        pattern = re.compile(rf'\b{re.escape(base)}\b', re.IGNORECASE)
        
        for source_name, rss_url in self.rss_sources.items():
            try:
                candidates = rss_url if isinstance(rss_url, (list, tuple)) else [rss_url]
                feed = None
                entries = []
                for cand in candidates:
                    f = feedparser.parse(cand)
                    if getattr(f, "entries", None):
                        feed = f
                        entries = f.entries
                        break
                if not entries:
                    continue
                for entry in entries[:20]:
                    title = entry.title if 'title' in entry else ''
                    summary = entry.summary if 'summary' in entry else ''
                    text = f"{title} {summary}"
                    
                    if pattern.search(text):
                        published = entry.published if 'published' in entry else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        results.append({
                            'source': source_name,
                            'title': title,
                            'link': entry.link,
                            'summary': summary,
                            'published': published
                        })
            except Exception as e:
                logger.error(f"Error searching {source_name}: {e}")
        if self.twitter_real_mode and self.kol_handles:
            try:
                for kol in self.kol_handles[:10]:
                    feed = feedparser.parse(f"https://nitter.net/{kol['handle']}/rss")
                    if not feed or not getattr(feed, "entries", None):
                        continue
                    for entry in feed.entries[:10]:
                        title = getattr(entry, "title", "")
                        summary = getattr(entry, "summary", "")
                        text = f"{title} {summary}".upper()
                        if base and base in text:
                            results.append({
                                'source': 'Twitter',
                                'author': kol['name'],
                                'title': title,
                                'link': getattr(entry, "link", kol['handle']),
                                'summary': summary,
                                'published': getattr(entry, "published", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                            })
            except Exception as e:
                logger.error(f"Error searching Twitter RSS: {e}")
        return results[:10]

    def _fetch_panews_newsflash_page(self):
        url = "https://www.panewslab.com/zh/newsflash"
        articles = []
        try:
            with httpx.Client(timeout=8) as client:
                r = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code != 200:
                    return []
                soup = BeautifulSoup(r.text, "html.parser")
                links = soup.select("a[href*='/newsflash/']")
                seen = set()
                for a in links[:30]:
                    href = a.get("href", "")
                    if not href or href in seen:
                        continue
                    seen.add(href)
                    link = href if href.startswith("http") else f"https://www.panewslab.com{href}"
                    title = a.get_text(strip=True)
                    parent = a.find_parent()
                    summary = ""
                    if parent:
                        summary = parent.get_text(" ", strip=True)
                    articles.append({
                        'source': 'PANews',
                        'title': title or 'PANews 快讯',
                        'link': link,
                        'summary': summary,
                        'published': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
        except Exception:
            return []
        return articles

    def _fetch_binance_announcements_page(self, limit=20):
        url = "https://www.binance.com/zh-CN/support/announcement"
        items = []
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded")
                try:
                    page.wait_for_load_state("networkidle", timeout=12000)
                except Exception:
                    pass
                anchors = page.locator("a[href*='/support/announcement/']").all()
                seen = set()
                for a in anchors[:100]:
                    try:
                        href = a.get_attribute("href") or ""
                        if not href or href in seen:
                            continue
                        seen.add(href)
                        link = href if href.startswith("http") else f"https://www.binance.com{href}"
                        title = a.inner_text().strip()
                        row = a.locator("xpath=ancestor::*[self::div or self::li or self::article]").first
                        summary = ""
                        try:
                            summary = row.inner_text().strip()
                        except Exception:
                            summary = title
                        if not title:
                            title = "Binance 公告"
                        items.append({
                            'source': 'Binance公告',
                            'title': title,
                            'link': link,
                            'summary': summary,
                            'published': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                        if len(items) >= limit:
                            break
                    except Exception:
                        continue
                try:
                    browser.close()
                except Exception:
                    pass
        except Exception:
            return []
        dedup = []
        seen = set()
        for it in items:
            k = it['link']
            if k in seen:
                continue
            seen.add(k)
            dedup.append(it)
        return dedup

    def scan_binance_alpha_listings(self, limit=10):
        items = []
        try:
            page_items = self._fetch_binance_announcements_page(limit=50)
            keys = ["上线", "上架", "开通交易", "开启交易", "将上线", "上线币安", "新增交易对", "上线现货", "上线合约"]
            for a in page_items:
                t = f"{a.get('title','')} {a.get('summary','')}"
                tx = t.replace("\u3000", " ")
                ok = False
                for k in keys:
                    if k in tx:
                        ok = True
                        break
                if ok:
                    items.append(a)
                    if len(items) >= limit:
                        break
        except Exception:
            return []
        return items
