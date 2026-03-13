import sqlite3
import logging
from datetime import datetime
from .config import Config
import re

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.db_path = Config.DB_PATH
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                plan_type TEXT DEFAULT 'free',
                risk_preference TEXT DEFAULT 'medium',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Signals table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                direction TEXT,
                heat_score REAL,
                volume_score REAL,
                narrative TEXT,
                risk_level TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Processed News table (to prevent duplicates)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS processed_news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                link TEXT UNIQUE,
                source TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
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
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_square_queue_text ON square_queue(text)')

        conn.commit()
        conn.close()
        logger.info("Database initialized.")
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS onchain_positions (
                    token_address TEXT PRIMARY KEY,
                    amount_wei INTEGER DEFAULT 0,
                    decimals INTEGER DEFAULT 18,
                    total_cost_usdt REAL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS onchain_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_address TEXT,
                    side TEXT,
                    amount_wei INTEGER,
                    usdt_value REAL,
                    tx_hash TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.commit()
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def add_user(self, user_id, plan_type='free'):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT OR IGNORE INTO users (user_id, plan_type) VALUES (?, ?)", (user_id, plan_type))
            conn.commit()
        except Exception as e:
            logger.error(f"Error adding user: {e}")
        finally:
            conn.close()
    
    def record_onchain_buy(self, token_address, received_wei, decimals, cost_usdt, tx_hash=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT amount_wei, total_cost_usdt, decimals FROM onchain_positions WHERE token_address = ?", (token_address,))
            row = cursor.fetchone()
            if row is None:
                cursor.execute("INSERT INTO onchain_positions (token_address, amount_wei, decimals, total_cost_usdt, updated_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)", (token_address, int(received_wei), int(decimals), float(cost_usdt)))
            else:
                amt, total_cost, dec = row
                new_amt = int(amt or 0) + int(received_wei)
                new_cost = float(total_cost or 0.0) + float(cost_usdt)
                cursor.execute("UPDATE onchain_positions SET amount_wei = ?, total_cost_usdt = ?, decimals = ?, updated_at = CURRENT_TIMESTAMP WHERE token_address = ?", (new_amt, new_cost, int(decimals), token_address))
            cursor.execute("INSERT INTO onchain_trades (token_address, side, amount_wei, usdt_value, tx_hash) VALUES (?, 'buy', ?, ?, ?)", (token_address, int(received_wei), float(cost_usdt), tx_hash or ''))
            conn.commit()
        except Exception as e:
            logger.error(f"Error record_onchain_buy: {e}")
        finally:
            conn.close()
    
    def record_onchain_sell(self, token_address, sold_wei, received_usdt, tx_hash=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT amount_wei, total_cost_usdt FROM onchain_positions WHERE token_address = ?", (token_address,))
            row = cursor.fetchone()
            if row is None:
                return 0.0
            amt, total_cost = row
            amt = int(amt or 0)
            total_cost = float(total_cost or 0.0)
            frac = (float(sold_wei) / float(amt)) if amt > 0 else 0.0
            proportional_cost = total_cost * frac
            new_amt = max(0, amt - int(sold_wei))
            new_cost = max(0.0, total_cost - proportional_cost)
            cursor.execute("UPDATE onchain_positions SET amount_wei = ?, total_cost_usdt = ?, updated_at = CURRENT_TIMESTAMP WHERE token_address = ?", (new_amt, new_cost, token_address))
            cursor.execute("INSERT INTO onchain_trades (token_address, side, amount_wei, usdt_value, tx_hash) VALUES (?, 'sell', ?, ?, ?)", (token_address, int(sold_wei), float(received_usdt), tx_hash or ''))
            conn.commit()
            realized_pnl = float(received_usdt) - proportional_cost
            return realized_pnl
        except Exception as e:
            logger.error(f"Error record_onchain_sell: {e}")
            return 0.0
        finally:
            conn.close()

    def get_user(self, user_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        conn.close()
        return user

    def update_risk_preference(self, user_id, risk_pref):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET risk_preference = ? WHERE user_id = ?", (risk_pref, user_id))
        conn.commit()
        conn.close()

    def add_signal(self, signal_data):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO signals (symbol, direction, heat_score, volume_score, narrative, risk_level)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                signal_data['symbol'],
                signal_data['direction'],
                signal_data['heat_score'],
                signal_data['volume_score'],
                signal_data['narrative'],
                signal_data['risk_level']
            ))
            conn.commit()
        except Exception as e:
            logger.error(f"Error adding signal: {e}")
        finally:
            conn.close()
            
    def get_recent_signals(self, limit=5):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM signals ORDER BY created_at DESC LIMIT ?", (limit,))
        signals = cursor.fetchall()
        conn.close()
        return signals

    def get_all_users(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users")
        users = [row[0] for row in cursor.fetchall()]
        conn.close()
        return users

    def is_news_processed(self, link):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM processed_news WHERE link = ?", (link,))
        exists = cursor.fetchone() is not None
        conn.close()
        return exists

    def mark_news_processed(self, link, source):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT OR IGNORE INTO processed_news (link, source) VALUES (?, ?)", (link, source))
            conn.commit()
        except Exception as e:
            logger.error(f"Error marking news processed: {e}")
        finally:
            conn.close()
    
    def claim_news_if_new(self, link, source):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT OR IGNORE INTO processed_news (link, source) VALUES (?, ?)", (link, source))
            conn.commit()
            return cursor.rowcount == 1
        except Exception as e:
            logger.error(f"Error claiming news: {e}")
            return False
        finally:
            conn.close()

    def _is_virtual_square_post(self, text):
        if not text:
            return True
        t = str(text)
        tl = t.lower()
        if "social heat score" in tl:
            return True
        if re.search(r"[A-Z0-9]{2,12}/USDT:USDT", t):
            return True
        if "币虎 | 📢 社交热度飙升" in t and "Verified by:" not in t and "Mentions:" not in t:
            return True
        if "币虎 | 💰 高额资金费率 |" in t:
            return True
        return False
    
    def add_square_post(self, text):
        if self._is_virtual_square_post(text):
            logger.warning(f"Rejected virtual square post: {str(text)[:120]}")
            return None
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            try:
                pass
            except Exception:
                pass
            cursor.execute("""
                SELECT id FROM square_queue
                WHERE text = ?
                AND (
                    status = 'pending'
                    OR (status = 'sent' AND sent_at IS NOT NULL AND sent_at >= datetime('now','-24 hours'))
                )
                LIMIT 1
            """, (text,))
            row = cursor.fetchone()
            if row is not None:
                return None
            cursor.execute("INSERT INTO square_queue (text, status) VALUES (?, 'pending')", (text,))
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error adding square post: {e}")
            return None
        finally:
            conn.close()

    def purge_virtual_pending_posts(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                UPDATE square_queue
                SET status = 'failed'
                WHERE status = 'pending'
                  AND (
                    lower(text) LIKE '%social heat score%'
                    OR text LIKE '%/USDT:USDT%'
                    OR (
                        text LIKE '%币虎 | 📢 社交热度飙升%'
                        AND text NOT LIKE '%Verified by:%'
                        AND text NOT LIKE '%Mentions:%'
                    )
                    OR text LIKE '%币虎 | 💰 高额资金费率 |%'
                  )
            """)
            conn.commit()
            return int(cursor.rowcount or 0)
        except Exception as e:
            logger.error(f"Error purging virtual posts: {e}")
            return 0
        finally:
            conn.close()
    
    def add_square_ad_post(self, text):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO square_queue (text, status) VALUES (?, 'pending')", (text,))
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error adding square ad post: {e}")
            return None
        finally:
            conn.close()
    
    def get_pending_square_posts(self, limit=10):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id, text, attempts FROM square_queue WHERE status = 'pending' ORDER BY created_at ASC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return rows
        except Exception as e:
            logger.error(f"Error fetching square posts: {e}")
            return []
        finally:
            conn.close()
    
    def mark_square_post_sent(self, post_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE square_queue SET status = 'sent', sent_at = CURRENT_TIMESTAMP WHERE id = ?", (post_id,))
            conn.commit()
        except Exception as e:
            logger.error(f"Error marking square post sent: {e}")
        finally:
            conn.close()
    
    def mark_square_post_approved(self, post_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE square_queue SET bot_approved = 1 WHERE id = ?", (post_id,))
            conn.commit()
        except Exception as e:
            logger.error(f"Error marking square post approved: {e}")
        finally:
            conn.close()
    
    def increment_square_attempt(self, post_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE square_queue SET attempts = attempts + 1 WHERE id = ?", (post_id,))
            conn.commit()
        except Exception as e:
            logger.error(f"Error incrementing square attempt: {e}")
        finally:
            conn.close()
    
    def mark_square_post_failed(self, post_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE square_queue SET status = 'failed' WHERE id = ?", (post_id,))
            conn.commit()
        except Exception as e:
            logger.error(f"Error marking square post failed: {e}")
        finally:
            conn.close()
