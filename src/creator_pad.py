import os
import time
import logging
import random
import re
from playwright.sync_api import sync_playwright

# Try to import Config, otherwise use defaults
try:
    from .config import Config
    from .ai_analyzer import AIAnalyzer
    # Try to import helpers from binance_square, but handle potential import errors
    try:
        from .binance_square import open_post_modal, find_modal_post_button
    except ImportError:
        # Fallback if binance_square cannot be imported directly (e.g. running as script)
        import sys
        sys.path.append(os.path.dirname(os.path.abspath(__file__)))
        from binance_square import open_post_modal, find_modal_post_button
except ImportError:
    try:
        from config import Config
        from ai_analyzer import AIAnalyzer
        from binance_square import open_post_modal, find_modal_post_button
    except ImportError:
        class Config:
            PLAYWRIGHT_HEADLESS = False
            LOG_LEVEL = "INFO"
        class AIAnalyzer:
            def generate_post(self, topic, length=200): return f"Hello {topic}!"
        def open_post_modal(page): return None
        def find_modal_post_button(ctx): return None

# Setup logging
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL, "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
URL = "https://www.binance.com/zh-CN/square/creatorpad?tab=campaigns"
# Use the same profile directory as other scripts to share session
PROFILE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "binance_profile")

class CreatorPadAutomator:
    def __init__(self):
        self.profile_dir = PROFILE_DIR
        self.headless = getattr(Config, "PLAYWRIGHT_HEADLESS", False)
        self.ai = AIAnalyzer()

    def run_loop(self, interval=3600):
        """Run the automation in a loop."""
        logger.info(f"Starting Creator Pad automation loop. Interval: {interval}s")
        while True:
            try:
                self.run_once()
            except Exception as e:
                logger.error(f"Error in automation loop: {e}")
            
            logger.info(f"Sleeping for {interval} seconds...")
            time.sleep(interval)

    def run_on_page(self, page):
        """Run automation on an existing page object."""
        logger.info(f"Running Creator Pad automation on existing page.")
        try:
            logger.info(f"Navigating to {URL}")
            page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            
            if self._is_logged_out(page):
                logger.warning("User logged out on existing page. Skipping.")
                return

            self._handle_check_in(page)
            
            # Loop a few times to ensure all claims/tasks are done (sometimes new ones unlock)
            for i in range(3):
                logger.info(f"Task cycle {i+1}/3")
                claims_done = self._handle_claims(page)
                tasks_done = self._handle_tasks(page)
                
                if not claims_done and not tasks_done:
                    logger.info("No more claims or tasks found.")
                    break
                
                # Refresh to see if status updated
                if i < 2:
                    page.reload(wait_until="domcontentloaded")
                    page.wait_for_timeout(5000)
            
            logger.info("Automation on existing page completed.")
        except Exception as e:
            logger.error(f"Error running on existing page: {e}")

    def run_once(self):
        """Run a single pass of the automation."""
        logger.info(f"Starting automation run with profile: {self.profile_dir}")
        
        with sync_playwright() as p:
            browser = None
            try:
                # Launch persistent context
                browser = p.chromium.launch_persistent_context(
                    user_data_dir=self.profile_dir,
                    headless=self.headless,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-setuid-sandbox"
                    ],
                    viewport={"width": 1280, "height": 800}
                )
                
                page = browser.pages[0] if browser.pages else browser.new_page()
                self.run_on_page(page)
                
            except Exception as e:
                logger.error(f"Critical error during run: {e}")
            finally:
                if browser:
                    browser.close()

    def _is_logged_out(self, page):
        # Heuristic: look for login buttons
        return page.locator("a[href*='/login'], button:has-text('Log In'), button:has-text('登录')").is_visible()

    def _handle_check_in(self, page):
        logger.info("Checking for 'Check In' buttons...")
        try:
            # Common selectors for check-in
            check_in_btn = page.locator("button:has-text('签到'), button:has-text('Check In')").first
            if check_in_btn.is_visible():
                check_in_btn.click()
                logger.info("Clicked 'Check In'")
                page.wait_for_timeout(3000)
                # Handle potential success modal
                self._close_modals(page)
            else:
                logger.info("No 'Check In' button found.")
        except Exception as e:
            logger.error(f"Error in check-in: {e}")

    def _handle_claims(self, page):
        logger.info("Checking for 'Claim' buttons...")
        clicked_any = False
        try:
            # Look for Claim buttons
            # Wait a bit for dynamic load
            page.wait_for_timeout(2000)
            claim_btns = page.locator("button:has-text('领取'), button:has-text('Claim')").all()
            if not claim_btns:
                logger.info("No 'Claim' buttons found.")
                return False

            for btn in claim_btns:
                try:
                    if btn.is_visible() and btn.is_enabled():
                        btn.click()
                        logger.info("Clicked 'Claim'")
                        clicked_any = True
                        page.wait_for_timeout(2000)
                        self._close_modals(page)
                except Exception as e:
                    logger.warning(f"Failed to click claim button: {e}")
            return clicked_any
        except Exception as e:
            logger.error(f"Error in claims: {e}")
            return False

    def _handle_tasks(self, page):
        logger.info("Checking for task buttons...")
        clicked_any = False
        try:
            # Scroll down to load more
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1000)
            page.evaluate("window.scrollTo(0, 0)")
            
            # Keywords for tasks that require action
            # "去完成" = Go complete
            # "浏览" = Browse/View
            # "分享" = Share
            # "发文" = Post
            task_keywords = ["发文", "Post", "去完成", "Go", "浏览", "View", "分享", "Share"]
            
            for keyword in task_keywords:
                btns = page.locator(f"button:has-text('{keyword}')").all()
                for btn in btns:
                    try:
                        if btn.is_visible() and btn.is_enabled():
                            clicked_any = True
                            # Check if it's a posting task
                            if keyword in ["发文", "Post"]:
                                self._handle_post_task(page, btn)
                                continue
                            
                            # Check if it opens a new page (common for "Go" tasks)
                            try:
                                with page.expect_popup(timeout=5000) as popup_info:
                                    btn.click()
                                new_page = popup_info.value
                                logger.info(f"Clicked '{keyword}' and opened new page.")
                                new_page.wait_for_load_state("domcontentloaded")
                                
                                # Check if it is a Robo/Activity sub-task page
                                if "creatorpad/robo" in new_page.url or "activity" in new_page.url:
                                    logger.info("Detected Robo/Activity page, running tasks recursively...")
                                    self._handle_robo_page(new_page)
                                else:
                                    # If it's a "Go" task that might be a post task
                                    if keyword in ["去完成", "Go"]:
                                        self._try_post_on_page(new_page)
                                    
                                time.sleep(random.uniform(5, 10)) # Simulate reading/viewing
                                new_page.close()
                                logger.info("Closed task page.")
                            except Exception:
                                # No popup, maybe just a click or modal
                                logger.info(f"Clicked '{keyword}' (no popup detected).")
                                pass
                            
                            page.wait_for_timeout(2000)
                            self._close_modals(page)
                    except Exception as e:
                        logger.warning(f"Failed to handle task button '{keyword}': {e}")
            return clicked_any
        except Exception as e:
            logger.error(f"Error in tasks: {e}")
            return False

    def _handle_robo_page(self, page):
        """Handle specific tasks on Robo/Activity pages."""
        logger.info("Handling Robo/Activity page tasks...")
        try:
            # 1. Claim any available rewards
            self._handle_claims(page)
            
            # 2. Look for 'Follow' buttons
            follow_btns = page.locator("button:has-text('Follow'), button:has-text('关注')").all()
            for btn in follow_btns:
                try:
                    if btn.is_visible() and btn.is_enabled():
                        btn.click()
                        logger.info("Clicked 'Follow'")
                        page.wait_for_timeout(1000)
                except Exception:
                    pass
            
            # 3. Handle other tasks (Vote, Share, etc.)
            # 'Vote' = 投票
            vote_btns = page.locator("button:has-text('Vote'), button:has-text('投票')").all()
            for btn in vote_btns:
                try:
                    if btn.is_visible() and btn.is_enabled():
                        btn.click()
                        logger.info("Clicked 'Vote'")
                        page.wait_for_timeout(1000)
                        self._close_modals(page)
                except Exception:
                    pass
            
            # 4. Recursively handle other tasks (View/Go)
            self._handle_tasks(page)

        except Exception as e:
            logger.error(f"Error handling Robo page: {e}")

    def _handle_post_task(self, page, btn):
        """Handle explicit post tasks."""
        logger.info("Handling post task...")
        try:
            # Try to get task description from nearby text
            # This is heuristic and might need adjustment
            description = "Crypto Market"
            try:
                # Look for preceding sibling or parent text
                parent = btn.locator("..")
                text = parent.inner_text()
                # Extract hashtags or key phrases
                hashtags = re.findall(r"#\w+", text)
                if hashtags:
                    description = " ".join(hashtags)
                else:
                    # Try to find meaningful text
                    lines = text.split('\n')
                    for line in lines:
                        if len(line) > 10 and "任务" not in line and "奖励" not in line:
                            description = line
                            break
            except Exception:
                pass
            
            logger.info(f"Task description: {description}")
            
            # Click the button
            try:
                # Check if it opens a modal or new page
                with page.expect_popup(timeout=3000) as popup_info:
                    btn.click()
                new_page = popup_info.value
                self._try_post_on_page(new_page, topic=description)
                new_page.close()
            except Exception:
                # Maybe modal
                btn.click()
                page.wait_for_timeout(2000)
                # Check for modal
                modal = open_post_modal(page)
                if modal:
                    content = self.ai.generate_post(description)
                    self._fill_and_post(page, content, modal)
        except Exception as e:
            logger.error(f"Error handling post task: {e}")

    def _try_post_on_page(self, page, topic="Crypto Market"):
        """Try to post on a new page."""
        try:
            page.wait_for_load_state("domcontentloaded")
            # Check if there is a post editor
            # Use find_modal_post_button to see if there is a post button
            post_btn = find_modal_post_button(page)
            if post_btn:
                logger.info("Found post button on new page. Generating content...")
                content = self.ai.generate_post(topic)
                self._fill_and_post(page, content)
        except Exception as e:
            logger.warning(f"Failed to post on new page: {e}")

    def _fill_and_post(self, page, text, modal=None):
        """Fill content and click post."""
        try:
            # Use logic similar to binance_square._post_text
            # We need to find the editor.
            ctx = modal if modal else page
            editor = None
            selectors = ["[contenteditable='true']", "div[role='textbox']", "textarea"]
            for sel in selectors:
                try:
                    loc = ctx.locator(sel).first
                    if loc.count() > 0 and loc.is_visible():
                        editor = loc
                        break
                except Exception:
                    continue
            
            if not editor:
                logger.warning("No editor found.")
                return

            logger.info(f"Filling editor with: {text[:20]}...")
            editor.click()
            page.wait_for_timeout(500)
            editor.fill(text)
            page.wait_for_timeout(1000)
            
            post_btn = find_modal_post_button(ctx)
            if post_btn:
                logger.info("Clicking post button...")
                post_btn.click()
                page.wait_for_timeout(3000)
                # Check for success toast
                # (Simplified check)
                logger.info("Post action completed.")
            else:
                logger.warning("Post button not found after filling.")

        except Exception as e:
            logger.error(f"Error in fill_and_post: {e}")

    def _close_modals(self, page):
        """Close any success/confirmation modals."""
        try:
            # Common close buttons
            close_btns = page.locator("button[aria-label='Close'], .css-1q4h8e6, svg.css-1pcq693").all()
            for btn in close_btns:
                if btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(500)
            
            # Click outside (sometimes works)
            # page.mouse.click(0, 0)
        except Exception:
            pass

if __name__ == "__main__":
    automator = CreatorPadAutomator()
    automator.run_loop(interval=1800) # Run every 30 minutes
