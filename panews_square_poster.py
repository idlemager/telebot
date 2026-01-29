import os
import random
import time
import re
from playwright.sync_api import sync_playwright
import sys
import logging
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    from src.config import Config
except Exception:
    class Config:
        LOG_LEVEL = "INFO"
        LOG_MAX_LEN = 1000

PANews_URL = "https://www.panewslab.com/zh/newsflash"
BlockBeats_URL = "https://www.theblockbeats.info/newsflash"
Binance_Square_URL = "https://www.binance.com/zh-CN/square"
PROFILE_DIR = os.path.join(os.path.dirname(__file__), "binance_profile")
FETCH_LIMIT = 5
TYPE_DELAY_MIN = 0.02
TYPE_DELAY_MAX = 0.08
POST_SLEEP_MIN = 0.8
POST_SLEEP_MAX = 2.2
POLL_SECONDS = 300
fmt = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
logging.basicConfig(format=fmt, level=getattr(logging, getattr(Config, "LOG_LEVEL", "INFO")), stream=sys.stdout)
class TruncatingFormatter(logging.Formatter):
    def format(self, record):
        max_len = getattr(Config, "LOG_MAX_LEN", 1000)
        orig_msg = record.msg
        orig_args = record.args
        try:
            msg = record.getMessage()
            if isinstance(msg, str) and len(msg) > max_len:
                record.msg = msg[:max_len] + "..."
                record.args = ()
            return super().format(record)
        finally:
            record.msg = orig_msg
            record.args = orig_args
for h in logging.getLogger().handlers:
    try:
        h.setFormatter(TruncatingFormatter(fmt))
    except Exception:
        pass
logger = logging.getLogger(__name__)

def log(msg):
    try:
        logger.info(str(msg))
    except Exception:
        try:
            print(str(msg))
        except Exception:
            pass

def sleep_rand(a, b):
    time.sleep(random.uniform(a, b))

def _collect_visible_lines(page):
    txt = ""
    try:
        txt = page.locator("main").inner_text(timeout=8000)
    except Exception:
        try:
            txt = page.locator("body").inner_text(timeout=8000)
        except Exception:
            return []
    lines = []
    for raw in txt.splitlines():
        s = raw.strip()
        if len(s) >= 10 and len(s) <= 240:
            lines.append(s)
    dedup = []
    seen = set()
    for s in lines:
        if s in seen:
            continue
        seen.add(s)
        dedup.append(s)
    return dedup

def fetch_panews_latest(page, limit=FETCH_LIMIT):
    page.goto(PANews_URL, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    items = []
    locs = [
        "article",
        "div[class*='news']",
        "section",
        "li",
    ]
    for sel in locs:
        try:
            count = page.locator(sel).count()
        except Exception:
            count = 0
        for i in range(min(count, 50)):
            try:
                t = page.locator(sel).nth(i).inner_text().strip()
            except Exception:
                continue
            if len(t) < 12:
                continue
            if "快讯" in t or "：" in t or "：" in t or "据" in t or "宣布" in t or "上线" in t:
                items.append(t)
            else:
                parts = [p.strip() for p in t.split("\n") if len(p.strip()) >= 12]
                if parts:
                    items.append(parts[0])
            if len(items) >= limit:
                break
        if len(items) >= limit:
            break
    if len(items) < 1:
        lines = _collect_visible_lines(page)
        for s in lines:
            if any(k in s for k in ["快讯", "据", "宣布", "上线", "集成", "发布", "交易", "融资"]):
                items.append(s)
            if len(items) >= limit:
                break
    cleaned = []
    seen = set()
    for it in items:
        s = " ".join(it.split())
        if s in seen:
            continue
        if len(s) > 220:
            s = s[:220]
        seen.add(s)
        cleaned.append(s)
    return cleaned[:limit]

def fetch_blockbeats_latest(page, limit=FETCH_LIMIT):
    page.goto(BlockBeats_URL, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    items = []
    locs = [
        "article",
        "section",
        "li",
        "div[class*='flash']",
        "div[class*='news']",
    ]
    for sel in locs:
        try:
            count = page.locator(sel).count()
        except Exception:
            count = 0
        for i in range(min(count, 60)):
            try:
                t = page.locator(sel).nth(i).inner_text().strip()
            except Exception:
                continue
            if len(t) < 12:
                continue
            if any(k in t for k in ["消息", "监测", "公布", "上线", "发布", "交易", "融资", "涨幅", "跌幅"]):
                items.append(t)
            else:
                parts = [p.strip() for p in t.split("\n") if len(p.strip()) >= 12]
                if parts:
                    items.append(parts[0])
            if len(items) >= limit:
                break
        if len(items) >= limit:
            break
    if len(items) < 1:
        lines = _collect_visible_lines(page)
        for s in lines:
            if len(s) >= 12:
                items.append(s)
            if len(items) >= limit:
                break
    cleaned = []
    seen = set()
    for it in items:
        s = " ".join(it.split())
        if s in seen:
            continue
        if len(s) > 220:
            s = s[:220]
        seen.add(s)
        cleaned.append(s)
    return cleaned[:limit]

def _open_square_composer(page):
    candidates = [
        
        "button:has-text('发文')",
        
        
        
        "[role='button']:has-text('发文')",
        
        "a:has-text('发文')",
    ]
    for sel in candidates:
        try:
            btn = page.locator(sel).first
            if btn.count() > 0:
                btn.scroll_into_view_if_needed()
                btn.click(timeout=5000)
                sleep_rand(POST_SLEEP_MIN, POST_SLEEP_MAX)
                break
        except Exception:
            continue
    editors = [
        "textarea",
        "[contenteditable='true']",
        "div[role='textbox']",
    ]
    for ed in editors:
        try:
            l = page.locator(ed).first
            if l.count() > 0:
                return l
        except Exception:
            continue
    return None

def _open_square_modal(page):
    triggers = [
        "button:has-text('文章')",
        "[role='button']:has-text('文章')",
        "a:has-text('文章')",
        "button:has-text('写文章')",
        "[role='button']:has-text('写文章')",
        "a:has-text('写文章')",
        "button:has-text('发文')",
        "[role='button']:has-text('发文')",
    ]
    for sel in triggers:
        try:
            t = page.locator(sel).first
            if t.count() > 0:
                t.scroll_into_view_if_needed()
                t.click(timeout=5000)
                sleep_rand(POST_SLEEP_MIN, POST_SLEEP_MAX)
                break
        except Exception:
            continue
    mods = [
        "[role='dialog']",
        "[aria-modal='true']",
        "div[class*='modal']",
        "div[class*='dialog']",
        "div[class*='Dialog']",
    ]
    for m in mods:
        try:
            loc = page.locator(m).last
            if loc.count() > 0:
                return loc
        except Exception:
            continue
    return None

def _open_sidebar_modal(page):
    containers = ["nav", "aside", "div[class*='sidebar']", "div[class*='SideBar']"]
    for c in containers:
        try:
            loc = page.locator(c)
            if loc.count() == 0:
                continue
            triggers = [
                "a:has-text('发文')",
                "[role='button']:has-text('发文')",
                "button:has-text('发文')",
                "a:has-text('文章')",
                "[role='button']:has-text('文章')",
                "button:has-text('文章')",
            ]
            for tsel in triggers:
                try:
                    t = loc.locator(tsel).first
                    if t.count() > 0:
                        t.scroll_into_view_if_needed()
                        t.click(timeout=5000)
                        sleep_rand(POST_SLEEP_MIN, POST_SLEEP_MAX)
                        break
                except Exception:
                    continue
        except Exception:
            continue
    try:
        dlg = page.locator("[role='dialog'], [aria-modal='true'], div[class*='modal'], div[class*='Dialog']").last
        if dlg.count() > 0:
            return dlg
    except Exception:
        pass
    return None

def _find_bottom_publish_button(page):
    sel = "button:has-text('发文'), [role='button']:has-text('发文')"
    loc = page.locator(sel)
    idx = -1
    best_y = -1
    try:
        count = loc.count()
    except Exception:
        count = 0
    for i in range(count):
        b = loc.nth(i)
        try:
            if hasattr(b, "is_visible"):
                if not b.is_visible():
                    continue
            bb = b.bounding_box()
            if bb and bb["y"] >= best_y:
                idx = i
                best_y = bb["y"]
        except Exception:
            continue
    if idx >= 0:
        return loc.nth(idx)
    alt = page.locator("button:has-text('发布'), [role='button']:has-text('发布'), button:has-text('发表'), [role='button']:has-text('发表')")
    try:
        if alt.count() > 0:
            return alt.last
    except Exception:
        pass
    return None

def _ai_pick_publish_button(page, modal):
    candidates = []
    try:
        if modal is not None and modal.count() > 0:
            mbtns = modal.locator("button:has-text('发文'), [role='button']:has-text('发文')")
            try:
                mc = mbtns.count()
            except Exception:
                mc = 0
            for i in range(mc):
                candidates.append(("modal", mbtns.nth(i)))
    except Exception:
        pass
    try:
        pbtn = _find_bottom_publish_button(page)
        if pbtn is not None:
            candidates.append(("page", pbtn))
    except Exception:
        pass
    best = None
    best_score = -1
    try:
        vp = page.viewport_size or {"width": 1000, "height": 800}
    except Exception:
        vp = {"width": 1000, "height": 800}
    for origin, btn in candidates:
        score = 0
        try:
            if hasattr(btn, "is_visible") and btn.is_visible():
                score += 3
            bb = btn.bounding_box()
            if bb:
                dy = vp["height"] - bb["y"]
                dx = vp["width"] - bb["x"]
                score += max(0, min(5, dy / 150))
                score += max(0, min(3, dx / 300))
            if origin == "modal":
                score += 4
            t = btn.inner_text().strip()
            if "发文" in t:
                score += 3
            if hasattr(btn, "is_enabled") and btn.is_enabled():
                score += 2
        except Exception:
            continue
        if score > best_score:
            best_score = score
            best = btn
    return best

def _type_human_like(page, target, text):
    try:
        target.click(timeout=4000)
    except Exception:
        pass
    try:
        target.fill("")
    except Exception:
        try:
            page.keyboard.press("Control+A")
            page.keyboard.press("Backspace")
        except Exception:
            pass
    for ch in text:
        page.keyboard.type(ch, delay=random.uniform(TYPE_DELAY_MIN, TYPE_DELAY_MAX))

def post_to_binance_square(page, content):
    page.goto(Binance_Square_URL, wait_until="load")
    try:
        page.wait_for_load_state("networkidle", timeout=12000)
    except Exception:
        pass
    modal = _open_sidebar_modal(page)
    if modal is None:
        modal = _open_square_modal(page)
    if modal is not None:
        try:
            editor = modal.locator("textarea[placeholder*='分享'], textarea[placeholder*='看法'], textarea, [contenteditable='true'], div[role='textbox']").first
        except Exception:
            editor = None
        if editor is None or editor.count() == 0:
            return False
        _type_human_like(page, editor, content)
        sleep_rand(POST_SLEEP_MIN, POST_SLEEP_MAX)
        b = _ai_pick_publish_button(page, modal)
    else:
        editor = _open_square_composer(page)
        if editor is None:
            editor = page.locator("textarea[placeholder*='分享'], textarea[placeholder*='看法'], textarea, [contenteditable='true'], div[role='textbox']").first
        if editor is None or editor.count() == 0:
            return False
        _type_human_like(page, editor, content)
        sleep_rand(POST_SLEEP_MIN, POST_SLEEP_MAX)
        b = _ai_pick_publish_button(page, None)
    if b is None:
        try:
            page.keyboard.press("Control+Enter")
            return True
        except Exception:
            return False
    try:
        b.scroll_into_view_if_needed()
    except Exception:
        pass
    for _ in range(6):
        try:
            if hasattr(b, "is_enabled"):
                if not b.is_enabled():
                    page.wait_for_timeout(700)
                    continue
            b.click(timeout=5000)
            try:
                time.sleep(0.8)
                m = page.locator("[role='dialog'], [aria-modal='true'], div[class*='modal'], div[class*='Dialog']").last
                if m.count() == 0:
                    return True
            except Exception:
                pass
            return True
        except Exception:
            page.wait_for_timeout(500)
    try:
        page.keyboard.press("Control+Enter")
        return True
    except Exception:
        return False

def build_single_post_text(item):
    s = " ".join(item.split())
    try:
        s = re.sub(r'^\s*panews(?:\s*快讯)?\s*[:：-]*\s*', '', s, flags=re.I)
        s = re.sub(r'^\s*blockbeats\s*消息[，,:：-]*\s*', '', s, flags=re.I)
    except Exception:
        pass
    if len(s) > 900:
        s = s[:900]
    return s

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(PROFILE_DIR, headless=False)
        page = browser.new_page()
        page.goto(Binance_Square_URL, wait_until="load")
        log("请在打开的浏览器中完成币安账号登录与验证，完成后回到终端按回车继续。")
        input()
        news_page = browser.new_page()
        block_page = browser.new_page()
        seen = set()
        try:
            initial_items = fetch_panews_latest(news_page, FETCH_LIMIT)
            initial_block = fetch_blockbeats_latest(block_page, FETCH_LIMIT)
            if not initial_items:
                log("未能抓取到快讯内容")
            else:
                for idx, it in enumerate(reversed(initial_items), 1):
                    content = build_single_post_text(it)
                    ok = post_to_binance_square(page, content)
                    if ok:
                        seen.add(" ".join(it.split()))
                        log(f"初始发布第 {idx} 条快讯")
                    else:
                        log(f"初始第 {idx} 条发布失败或未找到按钮")
                    sleep_rand(POST_SLEEP_MIN, POST_SLEEP_MAX)
            if initial_block:
                for it in reversed(initial_block):
                    content = build_single_post_text(it)
                    ok = post_to_binance_square(page, content)
                    if ok:
                        seen.add(" ".join(it.split()))
                        log("初始发布 BlockBeats 快讯一条")
                    else:
                        log("初始 BlockBeats 发布失败或未找到按钮")
                    sleep_rand(POST_SLEEP_MIN, POST_SLEEP_MAX)
            while True:
                try:
                    news_page.reload(wait_until="domcontentloaded")
                except Exception:
                    pass
                try:
                    news_page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                latest = fetch_panews_latest(news_page, FETCH_LIMIT)
                try:
                    block_page.reload(wait_until="domcontentloaded")
                except Exception:
                    pass
                try:
                    block_page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                latest_block = fetch_blockbeats_latest(block_page, FETCH_LIMIT)
                new_items = []
                for it in latest:
                    key = " ".join(it.split())
                    if key not in seen:
                        new_items.append(it)
                new_block_items = []
                for it in latest_block:
                    key = " ".join(it.split())
                    if key not in seen:
                        new_block_items.append(it)
                if new_items:
                    log(f"检测到新的快讯 {len(new_items)} 条，开始发布")
                    for it in reversed(new_items):
                        content = build_single_post_text(it)
                        ok = post_to_binance_square(page, content)
                        if ok:
                            seen.add(" ".join(it.split()))
                            log("已发布新的快讯一条")
                        else:
                            log("新的快讯发布失败或未找到按钮")
                        sleep_rand(POST_SLEEP_MIN, POST_SLEEP_MAX)
                if new_block_items:
                    log(f"检测到新的 BlockBeats 快讯 {len(new_block_items)} 条，开始发布")
                    for it in reversed(new_block_items):
                        content = build_single_post_text(it)
                        ok = post_to_binance_square(page, content)
                        if ok:
                            seen.add(" ".join(it.split()))
                            log("已发布新的 BlockBeats 快讯一条")
                        else:
                            log("新的 BlockBeats 快讯发布失败或未找到按钮")
                        sleep_rand(POST_SLEEP_MIN, POST_SLEEP_MAX)
                else:
                    log("暂无新的快讯")
                sleep_rand(POLL_SECONDS - 10, POLL_SECONDS + 20)
        except KeyboardInterrupt:
            pass
        finally:
            try:
                browser.close()
            except Exception:
                pass

if __name__ == "__main__":
    main()
