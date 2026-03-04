import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from .config import Config
from .engines import SignalEngine
from .database import Database
from .trading import TradingEngine
from .onchain import OnChainTradingEngine
from .missions import BinanceMissions
from .polymarket_watcher import PolymarketWatcher
import os
import time
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

class TrendPulseBot:
    def __init__(self):
        self.token = Config.TELEGRAM_BOT_TOKEN
        self.engine = SignalEngine()
        self.db = Database()
        self.whale_threshold_usd = Config.WHALE_THRESHOLD_USD
        self.trader = TradingEngine()
        self.onchain = OnChainTradingEngine()
        self.polymarket = PolymarketWatcher()
    
    def _is_group(self, update: Update):
        return update.effective_chat and update.effective_chat.type in ('group', 'supergroup')
        
    def run(self):
        if not self.token or self.token == "your_telegram_bot_token_here":
            logger.error("Telegram Bot Token not found or invalid in config! Please check .env file.")
            print("ERROR: Telegram Bot Token not set. Please set TELEGRAM_BOT_TOKEN in .env")
            return

        application = ApplicationBuilder().token(self.token).build()
        
        # Add JobQueue
        job_queue = application.job_queue
        # Schedule news check every 60 seconds
        job_queue.run_repeating(self.check_news, interval=60, first=10)
        # Schedule whale alerts check every 2 minutes
        job_queue.run_repeating(self.check_whale_alerts, interval=120, first=20)
        job_queue.run_repeating(self.housekeeping_cleanup, interval=21600, first=120)
        job_queue.run_repeating(self.post_advertisement, interval=Config.AD_INTERVAL_SECONDS, first=10)
        job_queue.run_repeating(self.check_funding_rates, interval=180, first=30)
        job_queue.run_repeating(self.check_binance_alpha, interval=300, first=40)
        job_queue.run_repeating(self.check_large_transfers, interval=180, first=50)
        job_queue.run_repeating(self.auto_trade_opportunities, interval=120, first=60)
        job_queue.run_repeating(self.auto_trade_onchain, interval=180, first=75)
        job_queue.run_repeating(self.monitor_onchain_positions, interval=240, first=120)
        job_queue.run_repeating(self.auto_run_missions, interval=600, first=180)
        job_queue.run_repeating(self.check_polymarket, interval=300, first=15)

        start_handler = CommandHandler('start', self.start)
        scan_handler = CommandHandler('scan', self.scan_social)
        analyze_handler = CommandHandler(['trend', 'risk'], self.analyze)
        stats_handler = CommandHandler('stats', self.stats)
        help_handler = CommandHandler('help', self.help)
        alpha_handler = CommandHandler('alpha', self.alpha)
        
        application.add_handler(start_handler)
        application.add_handler(scan_handler)
        application.add_handler(analyze_handler)
        application.add_handler(stats_handler)
        application.add_handler(help_handler)
        application.add_handler(CommandHandler('test_push', self.test_push))
        application.add_handler(alpha_handler)
        application.add_handler(CommandHandler('buytoken', self.buy_token))
        application.add_handler(CommandHandler('selltoken', self.sell_token))
        
        logger.info("Bot started...")
        print("Bot is running...")
        application.run_polling()

    async def check_news(self, context: ContextTypes.DEFAULT_TYPE):
        """Background task to check for new news"""
        logger.info("Scheduler: Checking for new news...")
        try:
            articles = self.engine.news.fetch_latest_news()
            if not articles:
                logger.info("Scheduler: No new articles found.")
                return

            logger.info(f"Scheduler: Found {len(articles)} new articles. Preparing to broadcast.")
            
            # Get all subscribed users (broadcasting to all for now)
            user_ids = self.db.get_all_users()
            if not user_ids:
                return

            for article in reversed(articles): # Send oldest to newest among the new ones
                # Atomically claim this news to avoid races across multiple bot instances
                if not self.db.claim_news_if_new(article['link'], article.get('source', 'Unknown')):
                    logger.info(f"Skipping duplicate (already processed): {article.get('title', '')}")
                    continue
                    
                source_emojis = {
                    'BlockBeats': "📰",
                    'PANews': "📢",
                    'InvestingCN': "📈",
                    'Binance公告': "🏦"
                }
                source_emoji = source_emojis.get(article.get('source'), "🗞️")
                
                # AI Analysis Section
                ai_section = ""
                if 'ai_analysis' in article and article['ai_analysis']:
                    analysis = article['ai_analysis']
                    impact_emoji = "🔥" if analysis['impact'] == 'High' else "⚡" if analysis['impact'] == 'Medium' else "ℹ️"
                    type_emoji = "🚀" if analysis['type'] == 'Listing' else "❌" if analysis['type'] == 'Delisting' else "📝"
                    
                    ai_section = f"\n\n🤖 **AI 智能分析**\n" \
                                 f"影响力: {impact_emoji} {analysis['impact']}\n" \
                                 f"类型: {type_emoji} {analysis['type']}\n" \
                                 f"摘要: {analysis['summary']}\n"

                msg = f"""
{source_emoji} **{article.get('source', 'News')} 快讯**

**{article['title']}**

{article['summary'][:200]}...
{ai_section}
🔗 [查看原文]({article['link']})
                """
                square_msg = article.get('summary') or f"{article['title']}"
                post_id = self.db.add_square_post(square_msg)
                
                for user_id in user_ids:
                    try:
                        chat = await context.bot.get_chat(user_id)
                        if chat.type in ('group', 'supergroup'):
                            await context.bot.send_message(chat_id=user_id, text=msg, parse_mode='Markdown')
                    except Exception as e:
                        logger.error(f"Failed to send news to {user_id}: {e}")
                        # In real app, might want to remove invalid users
                if post_id is not None:
                    try:
                        self.db.mark_square_post_approved(post_id)
                    except Exception:
                        pass
                
        except Exception as e:
            logger.error(f"Error in check_news job: {e}")

    async def housekeeping_cleanup(self, context: ContextTypes.DEFAULT_TYPE):
        try:
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            profile_dir = os.path.join(root_dir, "binance_profile")
            if os.path.isdir(profile_dir):
                now = time.time()
                ttl = 7 * 24 * 3600
                removed = 0
                for name in os.listdir(profile_dir):
                    if name.startswith("fail_") and name.endswith(".png"):
                        fp = os.path.join(profile_dir, name)
                        try:
                            mtime = os.path.getmtime(fp)
                            if now - mtime > ttl:
                                os.remove(fp)
                                removed += 1
                        except Exception:
                            continue
                if removed:
                    logger.info(f"Housekeeping removed {removed} old fail screenshots")
        except Exception as e:
            logger.error(f"Error in housekeeping_cleanup: {e}")

    async def test_push(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Manually trigger a test push of the latest news"""
        if not self._is_group(update):
            await context.bot.send_message(chat_id=update.effective_chat.id, text="该机器人仅在群组中可用。请在群聊中使用。")
            return
        await context.bot.send_message(chat_id=update.effective_chat.id, text="🔍 正在尝试抓取并推送最新一条快讯...")
        
        try:
            # We want to force fetch latest without updating last_published state, 
            # or just fetch and ignore state.
            # But fetch_latest_news uses state. 
            # So let's manually fetch one using internal logic or just create a new scanner instance?
            # Creating a new scanner instance is safest to not mess up state.
            from .news_scanner import NewsScanner
            temp_scanner = NewsScanner()
            
            # Reset state to ensure we get something if it exists
            # Actually, fetch_latest_news returns nothing on first run usually (initialization).
            # We need to hack it to return the first item.
            
            # Let's just fetch manually here for test
            import feedparser
            
            found_any = False
            for source_name, url in temp_scanner.rss_sources.items():
                feed = feedparser.parse(url)
                if feed.entries:
                    entry = feed.entries[0]
                    article = {
                        'source': source_name,
                        'title': entry.title,
                        'link': entry.link,
                        'summary': entry.summary if 'summary' in entry else ''
                    }
                    
                    source_emojis = {
                        'BlockBeats': "📰",
                        'PANews': "📢",
                        'InvestingCN': "📈",
                        'Binance公告': "🏦"
                    }
                    source_emoji = source_emojis.get(source_name, "🗞️")
                    
                    msg = f"""
{source_emoji} **{source_name} 测试推送**

**{article['title']}**

{article['summary'][:200]}...

🔗 [查看原文]({article['link']})
                    """
                    await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode='Markdown')
                    found_any = True
            
            if not found_any:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ 未能抓取到任何 RSS 数据。")
                
        except Exception as e:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ 测试出错: {e}")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_group(update):
            await context.bot.send_message(chat_id=update.effective_chat.id, text="该机器人仅在群组中可用。请在群聊中使用。")
            return
        chat_id = update.effective_chat.id
        self.db.add_user(chat_id)
        
        welcome_text = f"TrendPulse.Ai 已激活!\n\n本群将接收自动行情推送 (聪明钱/推特监控)。\n使用 /help 查看可用命令。"
            
        await context.bot.send_message(
            chat_id=chat_id,
            text=welcome_text
        )

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_group(update):
            await context.bot.send_message(chat_id=update.effective_chat.id, text="该机器人仅在群组中可用。请在群聊中使用。")
            return
        help_text = """
🚀 **TrendPulse 指令列表:**

/scan <币种> - 扫描该币种社交网络最新信息（附发布时间）
/trend <币种> - 全维度趋势分析
/risk <币种> - 风险分析
/stats - 查看最近信号
/settings - 设置偏好 (即将推出)
        """
        await context.bot.send_message(chat_id=update.effective_chat.id, text=help_text, parse_mode='Markdown')

    async def analyze(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_group(update):
            await context.bot.send_message(chat_id=update.effective_chat.id, text="该机器人仅在群组中可用。请在群聊中使用。")
            return
        if not context.args:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="请提供币种名称。例如: /trend BTC")
            return

        symbol = context.args[0].upper()
        # Handle cases where user might input just 'BTC' or 'BTCUSDT' or 'BTC/USDT'
        if '/' not in symbol:
             # Basic heuristic: append /USDT if not present
             if not symbol.endswith('USDT'):
                 symbol += '/USDT'
             else:
                 # Insert / before USDT if missing
                 symbol = symbol.replace('USDT', '/USDT')
            
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🔍 正在全维度扫描 {symbol}...")
        
        try:
            signal = self.engine.analyze_symbol(symbol)
            if not signal:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=f"无法获取 {symbol} 的数据。")
                return

            response = self._format_signal_message(signal)
            
            # Save signal if it's interesting (simplified logic)
            self.db.add_signal(signal)
            
            await context.bot.send_message(chat_id=update.effective_chat.id, text=response)
        except Exception as e:
            logger.error(f"Error in analyze: {e}")
            await context.bot.send_message(chat_id=update.effective_chat.id, text="扫描过程中发生错误。")

    async def scan_social(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_group(update):
            await context.bot.send_message(chat_id=update.effective_chat.id, text="该机器人仅在群组中可用。请在群聊中使用。")
            return
        if not context.args:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="请提供币种名称。例如: /scan BTC")
            return
        raw = context.args[0].upper()
        base = raw
        if '/' in base:
            base = base.split('/')[0]
        if base.endswith('USDT'):
            base = base.replace('USDT', '')
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🔎 正在扫描 {base} 社交网络最新动态...")
        try:
            items = self.engine.news.search_symbol_news(raw)
            if not items:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=f"未找到与 {base} 相关的最新动态。")
                return
            lines = ["📰 **社交网络最新信息:**", ""]
            for it in items[:10]:
                src = it.get('source', 'News')
                pub = it.get('published', '')
                title = it.get('title', '')
                link = it.get('link', '')
                author = it.get('author')
                head = f"{src}" + (f" · {author}" if author else "")
                lines.append(f"• {head} | {pub}")
                lines.append(f"{title}")
                if link:
                    lines.append(f"🔗 {link}")
                lines.append("")
            text = "\n".join(lines)
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error in scan_social: {e}")
            await context.bot.send_message(chat_id=update.effective_chat.id, text="扫描社交信息时发生错误。")

    async def check_polymarket(self, context: ContextTypes.DEFAULT_TYPE):
        """Background task to check for Polymarket alerts"""
        try:
            alerts = self.polymarket.check_market_movements()
            if not alerts:
                return
            
            user_ids = self.db.get_all_users()
            if not user_ids:
                return
                
            for alert in alerts:
                price_pct = alert['price'] * 100
                msg = f"""
🔮 **Polymarket 预测警报**

**事件:** {alert['event_title']}
**问题:** {alert['question']}
**结果:** {alert['outcome']} 概率突升至 **{price_pct:.1f}%** 🔥

🔗 [查看预测市场]({alert['link']})
"""
                for user_id in user_ids:
                    try:
                        await context.bot.send_message(chat_id=user_id, text=msg, parse_mode='Markdown')
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Error in check_polymarket: {e}")

    async def check_whale_alerts(self, context: ContextTypes.DEFAULT_TYPE):
        try:
            symbols = self.engine.market.list_usdt_pairs(limit=100)
            if not symbols:
                symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'PEPE/USDT', 'WIF/USDT']
            user_ids = self.db.get_all_users()
            if not user_ids:
                return
            for symbol in symbols:
                whale_data = self.engine.whale.scan_whale_activity(symbol)
                if not whale_data.get('has_activity'):
                    continue
                msg = f"""
🚨 **鲸鱼异动警报** 🚨
━━━━━━━━━━━━━━
**币种:** {symbol}
**动向:** {whale_data['summary']}

{whale_data['details']}

💡 *智能监控系统自动推送*
━━━━━━━━━━━━━━
                """
                square_msg = f"鲸鱼异动 {symbol} | {whale_data['summary']} | {whale_data['details']}"
                post_id = self.db.add_square_post(square_msg)
                for user_id in user_ids:
                    try:
                        chat = await context.bot.get_chat(user_id)
                        if chat.type in ('group', 'supergroup'):
                            await context.bot.send_message(chat_id=user_id, text=msg, parse_mode='Markdown')
                    except Exception as e:
                        logger.error(f"Failed to send whale alert to {user_id}: {e}")
                if post_id is not None:
                    try:
                        self.db.mark_square_post_approved(post_id)
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Error in check_whale_alerts: {e}")
    
    async def check_funding_rates(self, context: ContextTypes.DEFAULT_TYPE):
        try:
            syms = [s.strip() for s in Config.FUNDING_SYMBOLS.split(",") if s.strip()]
            if not syms:
                syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
            user_ids = self.db.get_all_users()
            if not user_ids:
                return
            for s in syms:
                rate = self.engine.market.fetch_current_funding_rate(s)
                if rate is None:
                    continue
                if abs(rate) < Config.FUNDING_RATE_THRESHOLD:
                    continue
                pct = rate * 100
                side = "正" if rate >= 0 else "负"
                msg = f"""
⚠️ **资金费率异常**
━━━━━━━━━━━━━━
**合约:** {s}
**费率:** {pct:.4f}%
**方向:** {side}

💡 *资金费率突破阈值，注意强平与挤兑风险*
━━━━━━━━━━━━━━
                """
                square_msg = f"资金费率异常 {s} | {pct:.4f}%"
                post_id = self.db.add_square_post(square_msg)
                for user_id in user_ids:
                    try:
                        chat = await context.bot.get_chat(user_id)
                        if chat.type in ('group', 'supergroup'):
                            await context.bot.send_message(chat_id=user_id, text=msg, parse_mode='Markdown')
                    except Exception as e:
                        logger.error(f"Failed to send funding alert to {user_id}: {e}")
                if post_id is not None:
                    try:
                        self.db.mark_square_post_approved(post_id)
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Error in check_funding_rates: {e}")
    
    async def check_binance_alpha(self, context: ContextTypes.DEFAULT_TYPE):
        try:
            if not Config.ALPHA_MONITOR_ENABLED:
                return
            items = self.engine.news.scan_binance_alpha_listings(limit=8)
            if not items:
                return
            user_ids = self.db.get_all_users()
            if not user_ids:
                return
            for a in items:
                msg = f"""
🏦 **币安新币监控**
━━━━━━━━━━━━━━
{a.get('title','')}

🔗 {a.get('link','')}
━━━━━━━━━━━━━━
                """
                square_msg = f"币安新币 {a.get('title','')}"
                post_id = self.db.add_square_post(square_msg)
                for user_id in user_ids:
                    try:
                        chat = await context.bot.get_chat(user_id)
                        if chat.type in ('group', 'supergroup'):
                            await context.bot.send_message(chat_id=user_id, text=msg)
                    except Exception as e:
                        logger.error(f"Failed to send alpha alert to {user_id}: {e}")
                if post_id is not None:
                    try:
                        self.db.mark_square_post_approved(post_id)
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Error in check_binance_alpha: {e}")
    
    async def check_large_transfers(self, context: ContextTypes.DEFAULT_TYPE):
        try:
            events = self.engine.whale.scan_large_transfers()
            if not events:
                return
            user_ids = self.db.get_all_users()
            if not user_ids:
                return
            for e in events:
                amt = e.get('amount_usd') or 0
                side = e.get('direction') or ''
                msg = f"""
💸 **大额转账监控**
━━━━━━━━━━━━━━
{e.get('title','')}

金额约 ${amt:,.0f} USD
方向 {side}
来源 {e.get('source','')}
🔗 {e.get('link','')}
━━━━━━━━━━━━━━
                """
                square_msg = f"大额转账 | {e.get('title','')} | ${amt:,.0f}"
                post_id = self.db.add_square_post(square_msg)
                for user_id in user_ids:
                    try:
                        chat = await context.bot.get_chat(user_id)
                        if chat.type in ('group', 'supergroup'):
                            await context.bot.send_message(chat_id=user_id, text=msg)
                    except Exception as ex:
                        logger.error(f"Failed to send transfer alert to {user_id}: {ex}")
                if post_id is not None:
                    try:
                        self.db.mark_square_post_approved(post_id)
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Error in check_large_transfers: {e}")
    
    async def alpha(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_group(update):
            await context.bot.send_message(chat_id=update.effective_chat.id, text="该机器人仅在群组中可用。请在群聊中使用。")
            return
        try:
            opps = self.engine.generate_opportunities()
            if not opps:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="当前暂无高置信度机会。")
                return
            lines = ["🚀 **实时机会清单**", ""]
            for o in opps[:8]:
                t = o.get('type')
                if t == 'funding_rate_extreme':
                    pct = o.get('rate', 0) * 100
                    lines.append(f"• 资金费率 | {o.get('symbol')} | {pct:.4f}% | 建议方向: {o.get('side')}")
                elif t == 'binance_alpha_listing':
                    lines.append(f"• 新币 | {o.get('title','')} | 链接 {o.get('link','')}")
                elif t == 'large_transfer':
                    amt = o.get('amount_usd') or 0
                    lines.append(f"• 大额转账 | {o.get('direction','')} | ${amt:,.0f} | 链接 {o.get('link','')}")
            text = "\n".join(lines)
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error in alpha command: {e}")
            await context.bot.send_message(chat_id=update.effective_chat.id, text="生成机会清单时发生错误。")
    
    async def auto_trade_opportunities(self, context: ContextTypes.DEFAULT_TYPE):
        try:
            if not self.trader.enabled:
                return
            syms = [s.strip() for s in getattr(Config, "TRADE_SYMBOLS", "").split(",") if s.strip()]
            if not syms:
                return
            for s in syms:
                sig = self.engine.analyze_symbol(s)
                if not sig:
                    continue
                o = self.trader.act_on_signal(s, sig)
                if o:
                    square_msg = f"AutoTrade {s} | {o.get('id','')} | {o.get('side','')}"
                    post_id = self.db.add_square_post(square_msg)
                    if post_id is not None:
                        try:
                            self.db.mark_square_post_approved(post_id)
                        except Exception:
                            pass
        except Exception as e:
            logger.error(f"Error in auto_trade_opportunities: {e}")
    
    async def auto_trade_onchain(self, context: ContextTypes.DEFAULT_TYPE):
        try:
            if not self.onchain.enabled:
                return
            opps = self.engine.generate_opportunities()
            if not opps:
                return
            wl = self.onchain.whitelist
            if not wl:
                return
            for o in opps:
                if o.get('type') == 'large_transfer' and o.get('direction') == 'inflow':
                    tx = self.onchain.buy_token_usdt(wl[0], min(self.onchain.max_usd, 10))
                    if tx:
                        self.db.record_onchain_buy(wl[0], tx.get('received_wei', 0), tx.get('decimals', 18), tx.get('cost_usdt', 0), tx_hash=tx.get('hash',''))
                        square_msg = f"OnChain Buy | {tx.get('hash','')}"
                        post_id = self.db.add_square_post(square_msg)
                        if post_id is not None:
                            try:
                                self.db.mark_square_post_approved(post_id)
                            except Exception:
                                pass
                    break
        except Exception as e:
            logger.error(f"Error in auto_trade_onchain: {e}")
    
    async def buy_token(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_group(update):
            await context.bot.send_message(chat_id=update.effective_chat.id, text="该机器人仅在群组中可用。请在群聊中使用。")
            return
        try:
            if not self.onchain.enabled:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="未启用链上交易。")
                return
            if len(context.args) < 2:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="用法: /buytoken <token_address> <usd>")
                return
            addr = context.args[0]
            usd = float(context.args[1])
            tx = self.onchain.buy_token_usdt(addr, usd)
            if tx:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=f"买入成功: {tx.get('hash','')}")
            else:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="买入失败或未满足白名单/余额。")
        except Exception as e:
            logger.error(f"Error in buy_token: {e}")
            await context.bot.send_message(chat_id=update.effective_chat.id, text="执行买入出错。")
    
    async def sell_token(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_group(update):
            await context.bot.send_message(chat_id=update.effective_chat.id, text="该机器人仅在群组中可用。请在群聊中使用。")
            return
        try:
            if not self.onchain.enabled:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="未启用链上交易。")
                return
            if len(context.args) < 2:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="用法: /selltoken <token_address> <percent>")
                return
            addr = context.args[0]
            pct = float(context.args[1])
            tx = self.onchain.sell_token_to_usdt(addr, pct)
            if tx:
                pnl = self.db.record_onchain_sell(addr, tx.get('sold_wei', 0), tx.get('received_usdt', 0), tx_hash=tx.get('hash',''))
                await context.bot.send_message(chat_id=update.effective_chat.id, text=f"卖出成功: {tx.get('hash','')} | 实现盈亏: ${pnl:,.2f}")
            else:
                await context.bot.send_message(chat_id=update.effective_chat.id, text="卖出失败或未满足白名单/余额。")
        except Exception as e:
            logger.error(f"Error in sell_token: {e}")
            await context.bot.send_message(chat_id=update.effective_chat.id, text="执行卖出出错。")
    
    async def monitor_onchain_positions(self, context: ContextTypes.DEFAULT_TYPE):
        try:
            if not self.onchain.enabled:
                return
            wl = self.onchain.whitelist
            if not wl:
                return
            # naive monitor: check the first token's current USDT value vs cost
            token = wl[0]
            # Fetch position
            conn = self.db.get_connection()
            cur = conn.cursor()
            cur.execute("SELECT amount_wei, total_cost_usdt, decimals FROM onchain_positions WHERE token_address = ?", (token,))
            row = cur.fetchone()
            conn.close()
            if not row:
                return
            amt_wei, total_cost, dec = row
            if amt_wei <= 0 or total_cost <= 0:
                return
            q = self.onchain._quote_out(int(amt_wei), [token, self.onchain.usdt])
            if not q or len(q) < 2:
                return
            current_usdt = float(q[-1]) / float(10 ** int(self.onchain._get_decimals(self.onchain.usdt)))
            change_pct = (current_usdt - float(total_cost)) / float(total_cost) * 100.0
            if change_pct <= -Config.STOP_LOSS_PCT or change_pct >= Config.TAKE_PROFIT_PCT:
                tx = self.onchain.sell_token_to_usdt(token, 1.0)
                if tx:
                    pnl = self.db.record_onchain_sell(token, tx.get('sold_wei', 0), tx.get('received_usdt', 0), tx_hash=tx.get('hash',''))
                    square_msg = f"OnChain Exit | {tx.get('hash','')} | PnL ${pnl:,.2f}"
                    post_id = self.db.add_square_post(square_msg)
                    if post_id is not None:
                        try:
                            self.db.mark_square_post_approved(post_id)
                        except Exception:
                            pass
        except Exception as e:
            logger.error(f"Error in monitor_onchain_positions: {e}")
    
    async def auto_run_missions(self, context: ContextTypes.DEFAULT_TYPE):
        try:
            if not Config.MISSIONS_ENABLED:
                return
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(None, BinanceMissions().run)
            if res and res.get("ok"):
                msg = "任务中心已尝试完成可点击任务"
            else:
                msg = "任务执行失败或未安装Playwright"
            post_id = self.db.add_square_post(msg)
            if post_id is not None:
                try:
                    self.db.mark_square_post_approved(post_id)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Error in auto_run_missions: {e}")
    
    async def post_advertisement(self, context: ContextTypes.DEFAULT_TYPE):
        try:
            try:
                load_dotenv(override=True)
            except Exception:
                pass
            enabled = os.getenv("AD_ENABLED", "true").lower() in ("1", "true", "yes")
            if not enabled:
                return
            ad = os.getenv("AD_TEXT", Config.AD_TEXT)
            post_id = self.db.add_square_ad_post(ad)
            if post_id is not None:
                self.db.mark_square_post_approved(post_id)
        except Exception as e:
            logger.error(f"Error in post_advertisement: {e}")

    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_group(update):
            await context.bot.send_message(chat_id=update.effective_chat.id, text="该机器人仅在群组中可用。请在群聊中使用。")
            return
        signals = self.db.get_recent_signals()
        if not signals:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="未找到最近的信号。")
            return
            
        text = "📊 **最近信号:**\n\n"
        for sig in signals:
            # id, symbol, direction, heat, vol, narrative, risk, created_at
            risk_map = {"High": "高", "Medium": "中", "Low": "低"}
            risk_cn = risk_map.get(sig[6], sig[6])
            
            text += f"• {sig[1]} ({sig[2]}): 风险 {risk_cn} | 热度 {sig[3]}\n"
            
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode='Markdown')

    def _format_signal_message(self, signal):
        # 🚀 TrendPulse 行情雷达 Template
        emoji_risk = "🟢" if signal['risk_level'] == "Low" else "🟡" if signal['risk_level'] == "Medium" else "🔴"
        
        # Mapping to Chinese
        risk_map = {"High": "高", "Medium": "中", "Low": "低"}
        risk_cn = risk_map.get(signal['risk_level'], signal['risk_level'])
        
        sentiment_map = {"bullish": "看多", "bearish": "看空", "neutral": "观望"}
        sentiment_cn = sentiment_map.get(signal['news_data']['sentiment'], signal['news_data']['sentiment'])
        
        direction_cn = sentiment_map.get(signal['direction'], signal['direction']) 

        # Format Whale Data
        whale_info = ""
        if 'whale_data' in signal and signal['whale_data']['has_activity']:
            wd = signal['whale_data']
            whale_info = f"""
🐋 **链上聪明钱:**
• 动向: {wd['summary']}
• 详情: {wd['details']}
"""
        else:
             whale_info = f"""
🐋 **链上聪明钱:**
• 动向: 暂无显著异动
"""

        msg = f"""
🚀 **TrendPulse 全维雷达**
━━━━━━━━━━━━━━
**币种:** `{signal['symbol']}`
**方向:** {direction_cn}
**叙事:** #{signal['narrative']}

📣 **消息面分析:**
• 热度指数: {signal['heat_score']}/100
• 提及增长: +{int(signal['news_data']['mentions_growth'])}%
• 市场情绪: {sentiment_cn}{signal['news_data'].get('extra_info', '')}

📈 **数据面异动:**
• 当前价格: `${signal['price']:.4f}`
• 成交量异动: {signal['volume_score']}%
{whale_info}
⚠️ **风控模型:**
• 风险等级: {risk_cn} {emoji_risk}

💡 **AI 综合结论:**
短期波动概率上升，建议结合风控操作。
━━━━━━━━━━━━━━
_不构成投资建议，请严格控制仓位_
        """
        return msg
