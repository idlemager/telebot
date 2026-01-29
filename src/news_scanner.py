import random
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
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

class NewsScanner:
    def __init__(self):
        self.narratives = ['AI', 'Meme', 'L2', 'DeFi', 'GameFi', 'RWA']
        self.rss_sources = {
            'BlockBeats': "https://api.theblockbeats.news/v2/rss/newsflash",
            'PANews': "https://www.panewslab.com/zh/rss/newsflash.xml",
            'InvestingCN': "https://cn.investing.com/rss/news_301.rss",
            'Binance公告': [
                "https://rsshub.app/binance/announcement/zh-CN",
                "https://rsshub.app/binance/announcement",
                "https://rsshub.rssforever.com/binance/announcement/zh-CN",
                "https://rsshub.rssforever.com/binance/announcement"
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

    def scan_news(self, symbol):
        heat_score = random.uniform(0, 100)
        sentiment = random.choice(['bullish', 'bearish', 'neutral'])
        narrative = random.choice(self.narratives)
        
        if symbol in ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']:
            heat_score += 20
            
        heat_score = min(100, heat_score)
        
        kol_mention_text = ""
        
        return {
            'heat_score': round(heat_score, 2),
            'sentiment': sentiment,
            'narrative': narrative,
            'mentions_growth': random.uniform(0, 500), # Percentage
            'kol_mentions': random.randint(0, 10),
            'extra_info': kol_mention_text
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
                
        return all_new_articles

    def search_symbol_news(self, symbol):
        results = []
        base = symbol.upper()
        if '/' in base:
            base = base.split('/')[0]
        if base.endswith('USDT'):
            base = base.replace('USDT', '')
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
                    text = f"{title} {summary}".upper()
                    if base and base in text:
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
