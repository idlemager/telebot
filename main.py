import logging
import sys
import traceback
import socket
import atexit
from logging import Formatter
import threading
import time

print("Starting main.py...", flush=True)

try:
    from src.bot import TrendPulseBot
    from src.config import Config

    # Configure Logging
    fmt = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    logging.basicConfig(format=fmt, level=getattr(logging, Config.LOG_LEVEL), stream=sys.stdout)
    class TruncatingFormatter(Formatter):
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
    logger = logging.getLogger()
    for h in logger.handlers:
        try:
            h.setFormatter(TruncatingFormatter(fmt))
        except Exception:
            pass

    if __name__ == '__main__':
        def acquire_lock():
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(('127.0.0.1', 58587))
                s.listen(1)
                return s
            except OSError:
                print("Another instance is running. Exiting.", flush=True)
                sys.exit(0)
        _lock = acquire_lock()
        atexit.register(lambda: _lock.close())
        print("Initializing Bot...", flush=True)
        bot = TrendPulseBot()
        try:
            import src.binance_square as square_worker
            _t = threading.Thread(target=square_worker.main, daemon=True)
            _t.start()
        except Exception:
            pass
        print("Running Bot...", flush=True)
        if Config.TELEGRAM_BOT_TOKEN and Config.TELEGRAM_BOT_TOKEN != "your_telegram_bot_token_here":
            bot.run()
        else:
            while True:
                try:
                    if _t and _t.is_alive():
                        time.sleep(1)
                    else:
                        time.sleep(5)
                except KeyboardInterrupt:
                    break
except Exception:
    traceback.print_exc()
