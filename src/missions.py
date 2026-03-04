import os
import json
from typing import Any, Dict
from .config import Config

class BinanceMissions:
    def __init__(self):
        self.cookies_raw = Config.BINANCE_COOKIES
        self.url = "https://www.binance.com/zh-CN/earn/mission-center"

    def run(self) -> Dict[str, Any]:
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            return {"ok": False, "error": "playwright_not_available"}
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                if self.cookies_raw:
                    try:
                        cookies = json.loads(self.cookies_raw)
                        context.add_cookies(cookies)
                    except Exception:
                        pass
                page = context.new_page()
                page.goto(self.url, wait_until="domcontentloaded")
                labels = ["做任务", "领取", "赚币", "去完成", "领取奖励"]
                for lb in labels:
                    try:
                        page.get_by_text(lb, exact=False).click(timeout=3000)
                    except Exception:
                        pass
                try:
                    btns = page.locator("button")
                    cnt = btns.count()
                    for i in range(min(cnt, 24)):
                        try:
                            t = btns.nth(i).inner_text()
                        except Exception:
                            t = ""
                        if any(k in t for k in ["任务", "领取", "奖励", "赚币"]):
                            try:
                                btns.nth(i).click(timeout=3000)
                            except Exception:
                                pass
                except Exception:
                    pass
                browser.close()
                return {"ok": True}
        except Exception:
            return {"ok": False, "error": "runtime_error"}
