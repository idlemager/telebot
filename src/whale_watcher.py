import random
import logging
import json
import os
import re
from datetime import datetime
try:
    import feedparser
except Exception:
    feedparser = None
try:
    import httpx
    from bs4 import BeautifulSoup
except Exception:
    httpx = None
    BeautifulSoup = None
from .config import Config

logger = logging.getLogger(__name__)

class WhaleWatcher:
    """
    Mock implementation of a Whale/Smart Money tracker.
    In a real production environment, this would integrate with:
    - Cielo Finance API / Webhooks
    - Debank Open API
    - Dune Analytics (via API or scraping)
    - Arkham Intelligence
    """
    
    def __init__(self):
        self.sources = [
            "Cielo Finance",
            "Drops Bot",
            "DexCheck",
            "SpotOnChain",
            "Arkham Alert"
        ]
        self.smart_money_list = self._load_smart_money_list()
        
    def _load_smart_money_list(self):
        """Load smart money list from json file"""
        try:
            # Get current directory of this file
            current_dir = os.path.dirname(os.path.abspath(__file__))
            file_path = os.path.join(current_dir, 'data', 'smart_money_list.json')
            
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    logger.info(f"Loaded {len(data)} smart money addresses.")
                    return data
            return []
        except Exception as e:
            logger.error(f"Error loading smart money list: {e}")
            return []
        
    def scan_whale_activity(self, symbol):
        """
        Scan for whale activity for a specific symbol.
        In real mode, parse RSS/快讯来源；否则回退到模拟。
        """
        base = symbol.upper()
        if '/' in base:
            base = base.split('/')[0]
        if base.endswith('USDT'):
            base = base.replace('USDT', '')
        if os.getenv("WHALE_REAL_MODE", "false").lower() in ("1", "true", "yes"):
            data = self._scan_real_sources(base)
            if data and data.get('has_activity'):
                return data
            return {
                'has_activity': False,
                'net_flow': 0,
                'whale_count': 0,
                'top_source': None,
                'summary': "暂无显著鲸鱼异动",
                'sentiment': 'neutral',
                'details': ""
            }
        has_activity = random.random() > 0.3
        if not has_activity:
            return {
                'has_activity': False,
                'net_flow': 0,
                'whale_count': 0,
                'top_source': None,
                'summary': "暂无显著鲸鱼异动",
                'sentiment': 'neutral',
                'details': ""
            }
        direction = random.choice(['inflow', 'outflow', 'accumulating'])
        whale_count = random.randint(1, 5)
        amount = random.uniform(100000, 5000000)
        source = random.choice(self.sources)
        smart_money_name = "Unknown Whale"
        if self.smart_money_list:
            sm_entry = random.choice(self.smart_money_list)
            smart_money_name = sm_entry['name']
        if direction == 'inflow':
            summary = f"检测到 {whale_count} 个聪明钱地址净买入"
            sentiment = "bullish"
            details = f"🔥 知名聪明钱 [{smart_money_name}] 在 {source} 上被监测到大额买入"
        elif direction == 'outflow':
            summary = f"检测到 {whale_count} 个鲸鱼地址抛售"
            sentiment = "bearish"
            details = f"⚠️ 知名聪明钱 [{smart_money_name}] 正在抛售"
        else:
            summary = f"聪明钱地址持续吸筹中"
            sentiment = "bullish"
            details = f"👀 监测到 [{smart_money_name}] 正在持续吸筹"
        return {
            'has_activity': True,
            'net_flow': amount if direction != 'outflow' else -amount,
            'whale_count': whale_count,
            'top_source': source,
            'summary': summary,
            'sentiment': sentiment,
            'details': f"{details} (${amount/1000:.1f}k)"
        }

    def _scan_real_sources(self, base):
        """
        解析真实快讯/RSS，提取与 base 相关的鲸鱼异动与金额。
        来源：BlockBeats、PANews 快讯页、（可选）RSS；取最近命中的一条。
        """
        entries = []
        try:
            if feedparser:
                rss_list = [
                    ("BlockBeats", "https://api.theblockbeats.news/v2/rss/newsflash"),
                    ("PANews", "https://www.panewslab.com/rss.xml"),
                ]
                for name, url in rss_list:
                    feed = feedparser.parse(url)
                    for e in feed.entries[:30]:
                        title = getattr(e, "title", "")
                        summary = getattr(e, "summary", "")
                        txt = f"{title} {summary}"
                        if self._is_whale_related(txt) and base in txt.upper():
                            entries.append((name, title, summary, getattr(e, "link", ""), getattr(e, "published", datetime.now().isoformat())))
        except Exception:
            pass
        try:
            if httpx and BeautifulSoup:
                page_entries = self._fetch_panews_newsflash_page()
                for a in page_entries[:50]:
                    txt = f"{a.get('title','')} {a.get('summary','')}"
                    if self._is_whale_related(txt) and base in txt.upper():
                        entries.append(("PANews", a.get('title',''), a.get('summary',''), a.get('link',''), a.get('published','')))
        except Exception:
            pass
        for src, title, summary, link, pub in entries:
            amt, sign = self._extract_amount_and_direction(f"{title} {summary}")
            if amt and amt >= Config.WHALE_THRESHOLD_USD:
                sentiment = "bullish" if sign >= 0 else "bearish"
                summary_cn = "净买入" if sign >= 0 else "抛售"
                return {
                    'has_activity': True,
                    'net_flow': amt if sign >= 0 else -amt,
                    'whale_count': 1,
                    'top_source': src,
                    'summary': f"检测到聪明钱{summary_cn}",
                    'sentiment': sentiment,
                    'details': f"{title} ({src})"
                }
        return None

    def _is_whale_related(self, text):
        t = text.lower()
        keys = ["whale", "鲸鱼", "聪明钱", "smart money", "lookonchain", "spotonchain", "spot on chain", "arkham"]
        return any(k in t for k in keys)

    def _extract_amount_and_direction(self, text):
        """
        从文本中解析金额（支持 $…k / $…M），以及方向（买入/抛售/inflow/outflow）。
        返回 (amount_usd, sign) sign: +1 买入, -1 卖出
        """
        amt = None
        m = re.search(r"\$\s*([0-9][0-9,\.]*)\s*([kKmM])", text)
        if m:
            num = m.group(1).replace(",", "").strip()
            unit = m.group(2)
            try:
                base = float(num)
                amt = base * (1000.0 if unit.lower() == 'k' else 1000000.0)
            except Exception:
                amt = None
        sign = 0
        t = text.lower()
        if any(w in t for w in ["买入", "inflow", "accumulat"]):
            sign = 1
        if any(w in t for w in ["抛售", "卖出", "outflow", "dump"]):
            sign = -1
        return amt, sign

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
                for a in links[:40]:
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
                        'title': title or 'PANews 快讯',
                        'link': link,
                        'summary': summary,
                        'published': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
        except Exception:
            return []
        return articles
