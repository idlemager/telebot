import os
import time
import threading
import queue
import logging
from playwright.sync_api import sync_playwright
import sqlite3
import re
import html
import sys
from dotenv import load_dotenv
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.config import Config
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

URL = "https://www.binance.com/zh-CN/square"
PROFILE_URL = "https://www.binance.com/zh-CN/square/profile/square-creator-3c1df46e1b0ed"
PROFILE_DIR = os.path.join(os.path.dirname(__file__), "..", "binance_profile")
X_PROFILE_URL = getattr(Config, "X_PROFILE_URL", "https://x.com/idlemage")
X_COMPOSE_URL = "https://x.com/compose/post"
logger = logging.getLogger(__name__)
DB_PATH = Config.DB_PATH

class BinanceSquarePublisher:
    def __init__(self):
        self._q = queue.Queue()
        self._thread = None
        self._stop = threading.Event()
        self._ready = False

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def publish(self, text: str):
        if not text:
            return
        self._q.put(text)
        if not self._thread or not self._thread.is_alive():
            self.start()

    def _worker(self):
        with sync_playwright() as p:
            browser = None
            page = None
            while not self._stop.is_set():
                try:
                    text = self._q.get(timeout=0.5)
                except queue.Empty:
                    continue
                if browser is None:
                    try:
                        browser = p.chromium.launch_persistent_context(PROFILE_DIR, headless=Config.PLAYWRIGHT_HEADLESS)
                        page = browser.new_page()
                        page.goto(URL, wait_until="load", timeout=30000)
                        self._ready = True
                    except Exception as e:
                        self._ready = False
                        logger.error(f"Init error: {e}")
                        try:
                            self._q.put(text)
                        except Exception:
                            pass
                        time.sleep(1.0)
                        continue
                if page is None:
                    try:
                        page = browser.new_page()
                        page.goto(URL, wait_until="load", timeout=30000)
                    except Exception as e:
                        logger.error(f"Page error: {e}")
                        try:
                            self._q.put(text)
                        except Exception:
                            pass
                        time.sleep(1.0)
                        continue
                ok = False
                try:
                    ok = self._post_text(page, text)
                except Exception as e:
                    logger.error(f"Post error: {e}")
                    ok = False
                if not ok:
                    try:
                        page.reload(wait_until="domcontentloaded", timeout=15000)
                    except Exception:
                        try:
                            page.goto(URL, wait_until="load", timeout=30000)
                        except Exception:
                            pass
                    try:
                        self._q.put(text)
                    except Exception:
                        pass
                time.sleep(1.0)
            try:
                if browser:
                    browser.close()
            except Exception:
                pass

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _post_text(self, page, text: str):
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        modal = open_post_modal(page)
        ctx = modal if modal is not None else page
        editor = None
        selectors = ["[contenteditable='true']", "[contenteditable=true]", "div[role='textbox']", "textarea"]
        for sel in selectors:
            try:
                loc = ctx.locator(sel).first
                if loc and loc.count() > 0:
                    editor = loc
                    break
            except Exception:
                continue
        if editor is None:
            return False
        try:
            editor.scroll_into_view_if_needed()
            editor.click(timeout=4000)
            try:
                page.keyboard.press("Control+A")
                page.keyboard.press("Delete")
            except Exception:
                pass
            try:
                editor.fill("")
            except Exception:
                pass
            try:
                editor.evaluate("el => { try { el.innerHTML = ''; } catch(_) {} try { if (typeof el.value !== 'undefined') el.value = ''; } catch(_) {} }")
            except Exception:
                pass
            try:
                page.keyboard.press("Control+A")
                page.keyboard.press("Delete")
            except Exception:
                pass
            try:
                editor.evaluate("(el, t) => { try { if (el.getAttribute && el.getAttribute('contenteditable')) { el.innerText = t; } else if (typeof el.value !== 'undefined') { el.value = t; } else { el.textContent = t; } } catch(_) {} }", text)
            except Exception:
                try:
                    editor.type(text, delay=10)
                except Exception:
                    page.keyboard.type(text, delay=10)
            try:
                cur = editor.inner_text().strip()
            except Exception:
                cur = ""
            if not cur:
                try:
                    cur = editor.input_value().strip()
                except Exception:
                    pass
            if cur and len(cur) > len(text) * 2 and cur.endswith(text):
                try:
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Delete")
                except Exception:
                    pass
                try:
                    editor.evaluate("(el, t) => { try { if (el.getAttribute && el.getAttribute('contenteditable')) { el.innerText = t; } else if (typeof el.value !== 'undefined') { el.value = t; } else { el.textContent = t; } } catch(_) {} }", text)
                except Exception:
                    pass
        except Exception:
            return False
        post_btn = find_modal_post_button(ctx)
        if post_btn is None:
            return False
        try:
            post_btn.scroll_into_view_if_needed()
            for _ in range(30):
                try:
                    dis = post_btn.get_attribute("disabled")
                    if dis is None and post_btn.is_enabled():
                        break
                except Exception:
                    break
                ctx.wait_for_timeout(200)
            post_btn.click(timeout=5000)
        except Exception:
            return False
        try:
            ctx.wait_for_timeout(2000)
            toast = ctx.locator("div:has-text('发布成功'), div:has-text('发文成功'), div:has-text('发帖成功'), [role='alert']:has-text('成功'), .bn-notification:has-text('成功')").first
            if toast and toast.count() > 0 and toast.is_visible():
                try:
                    for csel in ["button:has-text('关闭')", "[role='button']:has-text('关闭')", "button[aria-label='Close']", "[aria-label='Close']", "button:has-text('取消')", "[role='button']:has-text('取消')"]:
                        cl = ctx.locator(csel).first
                        if cl and cl.count() > 0 and cl.is_visible():
                            cl.click(timeout=2000)
                            break
                except Exception:
                    pass
                return True
            for _ in range(15):
                ctx.wait_for_timeout(1200)
                try:
                    toast = ctx.locator("div:has-text('发布成功'), div:has-text('发文成功'), div:has-text('发帖成功'), [role='alert']:has-text('成功'), .bn-notification:has-text('成功')").first
                    if toast and toast.count() > 0 and toast.is_visible():
                        try:
                            for csel in ["button:has-text('关闭')", "[role='button']:has-text('关闭')", "button[aria-label='Close']", "[aria-label='Close']", "button:has-text('取消')", "[role='button']:has-text('取消')"]:
                                cl = ctx.locator(csel).first
                                if cl and cl.count() > 0 and cl.is_visible():
                                    cl.click(timeout=2000)
                                    break
                        except Exception:
                            pass
                        return True
                except Exception:
                    pass
                try:
                    fail_toast = ctx.locator("div:has-text('发布失败'), div:has-text('发文失败'), div:has-text('发帖失败'), [role='alert']:has-text('失败')").first
                    if fail_toast and fail_toast.count() > 0 and fail_toast.is_visible():
                        return False
                except Exception:
                    pass
        except Exception:
            return False
        return False

def post_to_x(page, text: str):
    try:
        page.goto(X_PROFILE_URL, wait_until="load", timeout=30000)
    except Exception:
        try:
            page.goto(X_COMPOSE_URL, wait_until="load", timeout=30000)
        except Exception:
            return False
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    editor = None
    selectors = ["[contenteditable='true']", "[contenteditable=true]", "div[role='textbox']", "textarea"]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc and loc.count() > 0:
                editor = loc
                break
        except Exception:
            continue
    if editor is None:
        try:
            page.goto(X_COMPOSE_URL, wait_until="load", timeout=30000)
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            for sel in selectors:
                try:
                    loc = page.locator(sel).first
                    if loc and loc.count() > 0:
                        editor = loc
                        break
                except Exception:
                    continue
        except Exception:
            pass
    if editor is None:
        return False
    try:
        editor.scroll_into_view_if_needed()
        editor.click(timeout=4000)
        try:
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
        except Exception:
            pass
        page.keyboard.type(text, delay=10)
    except Exception:
        return False
    post_btn = None
    btn_selectors = [
        "button:has-text('Post'):not([disabled])",
        "[role='button']:has-text('Post'):not([disabled])",
        "button:has-text('Tweet'):not([disabled])",
        "[role='button']:has-text('Tweet'):not([disabled])",
        "button:has-text('发帖'):not([disabled])",
        "[role='button']:has-text('发帖'):not([disabled])",
        "[data-testid='tweetButtonInline']",
        "[data-testid='tweetButton']"
    ]
    for sel in btn_selectors:
        try:
            loc = page.locator(sel).first
            if loc and loc.count() > 0:
                post_btn = loc
                break
        except Exception:
            continue
    if post_btn is None:
        try:
            page.keyboard.press("Control+Enter")
            return True
        except Exception:
            return False
    try:
        post_btn.scroll_into_view_if_needed()
        for _ in range(20):
            try:
                dis = post_btn.get_attribute("disabled")
                if dis is None and post_btn.is_enabled():
                    break
            except Exception:
                break
            page.wait_for_timeout(200)
        post_btn.click(timeout=5000)
    except Exception:
        return False
    try:
        page.wait_for_timeout(1200)
    except Exception:
        pass
    return True

def open_post_modal(page):
    modal = None
    for msel in ["[role='dialog']", "div[aria-modal='true']", ".modal", ".bn-dialog", ".bn-modal"]:
        try:
            mloc = page.locator(msel).first
            if mloc and mloc.count() > 0:
                try:
                    if mloc.is_visible():
                        modal = mloc
                        break
                except Exception:
                    modal = mloc
                    break
        except Exception:
            continue
    if modal is None:
        for sb in [
            "button:has-text('发文')",
            "[role='button']:has-text('发文')",
            "header button:has-text('发文')",
            "header [role='button']:has-text('发文')",
            "nav button:has-text('发文')",
            "nav [role='button']:has-text('发文')",
            "aside button:has-text('发文')",
            "aside [role='button']:has-text('发文')"
        ]:
            try:
                sbloc = page.locator(sb).first
                if sbloc and sbloc.count() > 0:
                    try:
                        if sbloc.is_visible():
                            sbloc.scroll_into_view_if_needed()
                            sbloc.click(timeout=4000)
                            page.wait_for_timeout(800)
                            for msel in ["[role='dialog']", "div[aria-modal='true']", ".modal", ".bn-dialog", ".bn-modal"]:
                                mloc = page.locator(msel).first
                                if mloc and mloc.count() > 0:
                                    try:
                                        if mloc.is_visible():
                                            modal = mloc
                                            break
                                    except Exception:
                                        modal = mloc
                                        break
                            if modal is not None:
                                break
                    except Exception:
                        continue
            except Exception:
                continue
    return modal

def find_modal_post_button(ctx):
    btn = None
    selectors = [
        "footer button:has-text('发文'):not([disabled])",
        "footer [role='button']:has-text('发文'):not([disabled])",
        "footer button[data-bn-type='primary']",
        "button[data-bn-type='primary']:has-text('发文')",
        "[role='button'][data-bn-type='primary']:has-text('发文')",
        "button:has-text('发布'):not([disabled])",
        "[role='button']:has-text('发布'):not([disabled])",
        ".bn-dialog button:has-text('发文')",
        ".bn-modal button:has-text('发文')",
        ".bn-button:has-text('发文')",
        ".bn-button:has-text('发布')",
        ".bn-btn:has-text('发文')",
        ".bn-btn:has-text('发布')",
        "button:has-text('发帖'):not([disabled])",
        "[role='button']:has-text('发帖'):not([disabled])",
        "button:has-text('发送'):not([disabled])",
        "[role='button']:has-text('发送'):not([disabled])",
        "button:has-text('Post'):not([disabled])",
        "[role='button']:has-text('Post'):not([disabled])"
    ]
    for _ in range(40):
        for sel in selectors:
            try:
                loc = ctx.locator(sel).first
                if loc and loc.count() > 0:
                    try:
                        loc.wait_for(state="visible", timeout=1500)
                        if loc.is_visible() and loc.is_enabled():
                            btn = loc
                            return btn
                    except Exception:
                        btn = loc
                        return btn
            except Exception:
                continue
        try:
            ctx.wait_for_timeout(300)
        except Exception:
            pass
    try:
        candidates = ctx.locator("footer button, footer [role='button'], button[data-bn-type='primary'], [role='button'][data-bn-type='primary'], button, [role='button']").all()
        for c in candidates[::-1]:
            try:
                t = c.inner_text().strip()
                if any(x in t for x in ("发文", "发布", "发帖", "发送", "Post")) and c.is_visible() and c.is_enabled():
                    return c
            except Exception:
                continue
    except Exception:
        pass
    return btn
def ensure_square_queue_schema():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS square_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sent_at TIMESTAMP,
                attempts INTEGER DEFAULT 0,
                next_try_at TIMESTAMP,
                bot_approved INTEGER DEFAULT 0
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_square_queue_text ON square_queue(text)")
        cur.execute("PRAGMA table_info(square_queue)")
        cols = [row[1] for row in cur.fetchall()]
        if 'attempts' not in cols:
            cur.execute("ALTER TABLE square_queue ADD COLUMN attempts INTEGER DEFAULT 0")
        if 'sent_at' not in cols:
            cur.execute("ALTER TABLE square_queue ADD COLUMN sent_at TIMESTAMP")
        if 'next_try_at' not in cols:
            cur.execute("ALTER TABLE square_queue ADD COLUMN next_try_at TIMESTAMP")
        if 'bot_approved' not in cols:
            cur.execute("ALTER TABLE square_queue ADD COLUMN bot_approved INTEGER DEFAULT 0")
        conn.commit()
    finally:
        conn.close()

def claim_pending(limit=5):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    claimed = []
    try:
        cur.execute("""
            SELECT id, text, attempts FROM square_queue
            WHERE status = 'pending'
              AND bot_approved = 1
              AND (next_try_at IS NULL OR next_try_at <= CURRENT_TIMESTAMP)
            ORDER BY created_at ASC
            LIMIT 1
        """)
        row = cur.fetchone()
        if row:
            pid, text, attempts = row
            cur.execute("UPDATE square_queue SET status = 'processing' WHERE id = ? AND status = 'pending'", (pid,))
            if cur.rowcount and cur.rowcount > 0:
                claimed.append((pid, text, attempts))
        conn.commit()
        return claimed
    finally:
        conn.close()

def mark_sent(post_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute("UPDATE square_queue SET status = 'sent', sent_at = CURRENT_TIMESTAMP, next_try_at = NULL WHERE id = ?", (post_id,))
        conn.commit()
    finally:
        conn.close()

def inc_attempt(post_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute("UPDATE square_queue SET attempts = attempts + 1 WHERE id = ?", (post_id,))
        conn.commit()
    finally:
        conn.close()

def reset_pending(post_id, delay_seconds=None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        if delay_seconds and delay_seconds > 0:
            cur.execute("UPDATE square_queue SET status = 'pending', next_try_at = datetime('now', ?) WHERE id = ?", (f'+{int(delay_seconds)} seconds', post_id))
        else:
            cur.execute("UPDATE square_queue SET status = 'pending', next_try_at = NULL WHERE id = ?", (post_id,))
        conn.commit()
    finally:
        conn.close()

def mark_failed(post_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute("UPDATE square_queue SET status = 'failed' WHERE id = ?", (post_id,))
        conn.commit()
    finally:
        conn.close()
def already_sent(text):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute("SELECT 1 FROM square_queue WHERE text = ? AND status = 'sent' AND sent_at IS NOT NULL AND sent_at >= datetime('now','-25 minutes') LIMIT 1", (text,))
        row = cur.fetchone()
        return row is not None
    finally:
        conn.close()

def sanitize_text(text):
    if not text:
        return ""
    raw = text
    ps = re.findall(r"<p[^>]*>(.*?)</p>", raw, flags=re.IGNORECASE | re.DOTALL)
    if ps:
        cleaned = []
        for p in ps:
            p = p.replace("</p><p>", "\n").replace("<br />", "\n").replace("<br/>", "\n").replace("<br>", "\n")
            p = re.sub(r"<[^>]+>", "", p)
            p = html.unescape(p)
            p = re.sub(r"(?i)\bokx\b", "", p)
            p = re.sub(r"[ \t]+", " ", p)
            p = p.strip()
            if p:
                cleaned.append(p)
        s = "\n".join(cleaned)
        if len(s) > 1800:
            s = s[:1800]
        return s
    t = raw.replace("</p><p>", "\n").replace("<br />", "\n").replace("<br/>", "\n").replace("<br>", "\n")
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    t = re.sub(r"(?i)\bokx\b", "", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = t.strip()
    if len(t) > 1800:
        t = t[:1800]
    return t

def main():
    ensure_square_queue_schema()
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(PROFILE_DIR, headless=Config.PLAYWRIGHT_HEADLESS)
        page = browser.new_page()
        page.goto(PROFILE_URL, wait_until="load")
        last_ad_ts = 0
        while True:
            try:
                load_dotenv(override=True)
                ad_text = os.getenv("AD_TEXT")
                try:
                    ad_interval = int(os.getenv("AD_INTERVAL_SECONDS", "0") or "0")
                except Exception:
                    ad_interval = 0
                ad_enabled = (os.getenv("AD_ENABLED", "true").lower() in ("1", "true", "yes"))
                if ad_enabled and ad_text and ad_interval > 0:
                    now = time.time()
                    if (now - last_ad_ts) >= int(ad_interval):
                        try:
                            conn = sqlite3.connect(DB_PATH)
                            cur = conn.cursor()
                            cur.execute("INSERT INTO square_queue (text, status, bot_approved) VALUES (?, 'pending', 1)", (ad_text,))
                            conn.commit()
                            last_ad_ts = now
                        except Exception:
                            pass
                        finally:
                            try:
                                conn.close()
                            except Exception:
                                pass
            except Exception:
                pass
            posts = claim_pending(limit=1)
            try:
                logger.info(f"[square] pending-approved batch: {len(posts)}")
            except Exception:
                pass
            if not posts:
                time.sleep(3)
                continue
            for pid, text, attempts in posts:
                ok = False
                reason = None
                try:
                    if already_sent(text):
                        mark_failed(pid)
                        ok, reason = False, "duplicate"
                    else:
                        clean = sanitize_text(text)
                        if not clean or len(clean.strip()) == 0:
                            ok, reason = False, "empty"
                        else:
                            ok = BinanceSquarePublisher()._post_text(page, clean)
                            reason = None if ok else "failed"
                except Exception:
                    ok = False
                    reason = "exception"
                if ok:
                    mark_sent(pid)
                    try:
                        logger.info(f"[square] sent {pid}")
                    except Exception:
                        pass
                else:
                    inc_attempt(pid)
                    if (attempts + 1) >= 3:
                        mark_failed(pid)
                        try:
                            logger.info(f"[square] failed {pid} and marked failed")
                        except Exception:
                            pass
                    else:
                        if reason == "rate_limited":
                            delay = 180
                        elif reason == "network":
                            delay = 60
                        elif reason == "empty":
                            delay = 0
                        else:
                            delay = min(300, 20 * (attempts + 1))
                        reset_pending(pid, delay_seconds=delay)
                        try:
                            logger.info(f"[square] retry {pid} after {delay}s due to {reason}")
                        except Exception:
                            pass
            time.sleep(2)

if __name__ == "__main__":
    main()
