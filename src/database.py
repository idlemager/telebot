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
    
    def add_square_post(self, text):
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
