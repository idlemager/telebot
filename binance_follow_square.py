import os
import time
from playwright.sync_api import sync_playwright
import sqlite3
import re
import html
import sys
import logging
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    from src.config import Config
except Exception:
    class Config:
        LOG_LEVEL = "INFO"
        LOG_MAX_LEN = 1000

URL = "https://www.binance.com/zh-CN/square"
PROFILE_URL = "https://www.binance.com/zh-CN/square/profile/square-creator-3c1df46e1b0ed"
PROFILE_DIR = os.path.join(os.path.dirname(__file__), "binance_profile")
DB_PATH = os.path.join(os.path.dirname(__file__), "trendpulse.db")
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
            p = re.sub(r"^\s*(BlockBeats\s*快讯[:]?\s*)", "", p, flags=re.IGNORECASE)
            p = re.sub(r"[ \t]+", " ", p)
            p = p.strip()
            if p:
                cleaned.append(p)
        return "\n".join(cleaned)
    t = raw.replace("</p><p>", "\n").replace("<br />", "\n").replace("<br/>", "\n").replace("<br>", "\n")
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    t = re.sub(r"^\s*(BlockBeats\s*快讯[:]?\s*)", "", t, flags=re.IGNORECASE)
    t = re.sub(r"[ \t]+", " ", t)
    t = t.strip()
    return t

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
        "button:has-text('发文'):not([disabled])",
        "[role='button']:has-text('发文'):not([disabled])",
        "button:has-text('发布'):not([disabled])",
        "[role='button']:has-text('发布'):not([disabled])",
        "[data-bn-type='primary']:has-text('发文')",
        "[data-bn-type='primary']:has-text('发布')",
        "button:has-text('发帖'):not([disabled])",
        "[role='button']:has-text('发帖'):not([disabled])",
        "button:has-text('发送'):not([disabled])",
        "[role='button']:has-text('发送'):not([disabled])",
        "button:has-text('Post'):not([disabled])",
        "[role='button']:has-text('Post'):not([disabled])",
        ".bn-button:has-text('发文')",
        ".bn-button:has-text('发布')",
        ".bn-btn:has-text('发文')",
        ".bn-btn:has-text('发布')",
        "[data-bn-type='primary']",
        "footer button[data-bn-type='primary']",
        "[role='dialog'] button[data-bn-type='primary']",
        "[aria-modal='true'] button[data-bn-type='primary']",
        "[role='dialog'] .bn-button",
        "[aria-modal='true'] .bn-button"
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
        candidates = ctx.locator("button, [role='button']").all()
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

def clear_title_fields(ctx, page):
    sels = [
        "input[placeholder*='标题']",
        "textarea[placeholder*='标题']",
        "input[aria-label*='标题']",
        "textarea[aria-label*='标题']",
        "input[placeholder*='Title']",
        "textarea[placeholder*='Title']",
        "input[aria-label*='Title']",
        "textarea[aria-label*='Title']"
    ]
    for sel in sels:
        try:
            loc = ctx.locator(sel).first
            if loc and loc.count() > 0:
                try:
                    loc.wait_for(state="visible", timeout=4000)
                    if loc.is_visible() and loc.is_enabled():
                        loc.scroll_into_view_if_needed()
                        loc.click(timeout=3000)
                        try:
                            page.keyboard.press("Control+A")
                            page.keyboard.press("Delete")
                        except Exception:
                            pass
                        try:
                            loc.fill("")
                        except Exception:
                            pass
                except Exception:
                    continue
        except Exception:
            continue

def snapshot_on_failure(page, pid, reason):
    try:
        ts = int(time.time())
        out_dir = PROFILE_DIR
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception:
            pass
        fname = os.path.join(out_dir, f"fail_{pid}_{reason}_{ts}.png")
        page.screenshot(path=fname, full_page=True)
    except Exception:
        pass

def fetch_pending(limit=5):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, text, attempts FROM square_queue WHERE status = 'pending' ORDER BY created_at ASC LIMIT ?", (limit,))
        rows = cur.fetchall()
        return rows
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
              AND (next_try_at IS NULL OR next_try_at <= CURRENT_TIMESTAMP)
              AND bot_approved = 1
            ORDER BY created_at ASC
            LIMIT ?
        """, (limit,))
        rows = cur.fetchall()
        for pid, text, attempts in rows:
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

def post_text(page, text):
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    modal = open_post_modal(page)
    ctx = modal if modal is not None else page
    if modal is None:
        return False
    try:
        clear_title_fields(ctx, page)
    except Exception:
        pass
    editor = None
    selectors = ["[contenteditable='true']", "[contenteditable=true]", "div[role='textbox']", "textarea"]
    for sel in selectors:
        try:
            loc = ctx.locator(sel).first
            if loc and loc.count() > 0:
                try:
                    loc.wait_for(state="visible", timeout=12000)
                    if loc.is_visible():
                        editor = loc
                        break
                except Exception:
                    editor = loc
                    break
        except Exception:
            continue
    if editor is None:
        return False
    try:
        editor.scroll_into_view_if_needed()
        editor.click(timeout=4000)
        # Clear previous content
        try:
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
        except Exception:
            pass
        page.keyboard.type(text, delay=10)
    except Exception:
        return False
    post_btn = find_modal_post_button(ctx)
    if post_btn is None:
        return False, "no_button"
    try:
        post_btn.scroll_into_view_if_needed()
        # Wait until button enabled (attribute check)
        for _ in range(40):
            try:
                dis = post_btn.get_attribute("disabled")
                if dis is None and post_btn.is_enabled():
                    break
            except Exception:
                break
            ctx.wait_for_timeout(250)
        post_btn.click(timeout=5000)
    except Exception:
        return False, "click_error"
    # Wait for editor to clear as success signal
    try:
        page.wait_for_timeout(2500)
        try:
            toast = ctx.locator("div:has-text('发布成功'), div:has-text('发文成功'), div:has-text('发帖成功'), [role='alert']:has-text('成功'), .bn-notification:has-text('成功')").first
            if toast and toast.count() > 0:
                if toast.is_visible():
                    return True, None
        except Exception:
            pass
        # If posting in progress, button may become disabled; poll longer for success
        for _ in range(15):
            page.wait_for_timeout(1500)
            try:
                toast = ctx.locator("div:has-text('发布成功'), div:has-text('发文成功'), div:has-text('发帖成功'), [role='alert']:has-text('成功'), .bn-notification:has-text('成功')").first
                if toast and toast.count() > 0 and toast.is_visible():
                    return True, None
            except Exception:
                pass
            # Detect explicit failure toast and only then fail
            try:
                fail_toast = ctx.locator("div:has-text('发布失败'), div:has-text('发文失败'), div:has-text('发帖失败'), [role='alert']:has-text('失败')").first
                if fail_toast and fail_toast.count() > 0 and fail_toast.is_visible():
                    try:
                        msg = fail_toast.inner_text().strip()
                    except Exception:
                        msg = ""
                    reason = "rate_limited" if ("频繁" in msg or "稍后" in msg) else ("empty" if "内容" in msg and "空" in msg else "failed")
                    return False, reason
            except Exception:
                pass
            try:
                txt_after = editor.inner_text().strip()
                if len(txt_after) == 0 or txt_after != text.strip():
                    return True, None
            except Exception:
                return True, None
        if modal is not None:
            try:
                if not modal.is_visible():
                    return True, None
            except Exception:
                return True, None
        txt_after_final = editor.inner_text().strip()
        if len(txt_after_final) == 0 or txt_after_final != text.strip():
            return True, None
    except Exception:
        return True, None
    return False, "unknown_timeout"

def main():
    ensure_square_queue_schema()
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(PROFILE_DIR, headless=False)
        page = browser.new_page()
        page.goto(PROFILE_URL, wait_until="load")
        log("请在打开的浏览器中完成登录并保持登录状态。")
        while True:
            posts = claim_pending(limit=1)
            if not posts:
                time.sleep(3)
                continue
            for pid, text, attempts in posts:
                ok = False
                reason = None
                try:
                    clean = sanitize_text(text)
                    if not clean or len(clean.strip()) == 0:
                        ok, reason = False, "empty"
                    else:
                        ok, reason = post_text(page, clean)
                except Exception:
                    ok = False
                    reason = "exception"
                if ok:
                    mark_sent(pid)
                    log(f"已发布 {pid}")
                else:
                    inc_attempt(pid)
                    snapshot_on_failure(page, pid, reason or "unknown")
                    if (attempts + 1) >= 3:
                        mark_failed(pid)
                        log(f"发布失败且已放弃 {pid}")
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
                        log(f"发布失败 {pid}（{reason}），已进入冷却 {delay}s 后重试")
            time.sleep(2)

if __name__ == "__main__":
    main()
