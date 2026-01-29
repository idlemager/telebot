import feedparser
import requests
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

url = "https://www.panewslab.com/rss.xml"
logger.info(f"Testing RSS fetch from {url}")

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

try:
    response = requests.get(url, headers=headers)
    logger.info(f"Status Code: {response.status_code}")
    
    if response.status_code == 200:
        feed = feedparser.parse(response.content)
        if feed.entries:
            logger.info(f"Success! Found {len(feed.entries)} entries.")
            logger.info(f"Latest: {feed.entries[0].title}")
            logger.info(f"Link: {feed.entries[0].link}")
        else:
            logger.warning("No entries found in feed parsing.")
            # logger.info(f"Content: {response.text[:500]}")
    else:
        logger.error("Failed to fetch URL")

except Exception as e:
    logger.error(f"Error: {e}")
