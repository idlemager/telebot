# TrendPulse.Ai Bot Setup Guide

## 1. Installation

Ensure you have Python 3.10+ installed.

```bash
pip install -r requirements.txt
```

## 2. Configuration

1. Open `.env` file.
2. Set your Telegram Bot Token:
   ```
   TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
   ```
   (You can get a token from @BotFather on Telegram)

3. (Optional) Set Binance API keys if you want real trading data (otherwise it runs in Mock Mode):
   ```
   BINANCE_API_KEY=your_key
   BINANCE_API_SECRET=your_secret
   ```

## 3. Running the Bot

Run the main script:

```bash
python main.py
```

The bot will start and print "Bot started...".

## 4. Testing without Telegram

You can test the signal engine logic without a bot token by running:

```bash
python test_engine.py
```

## 5. Available Commands

- `/start` - Register and welcome.
- `/scan <symbol>` - Scan a coin (e.g., `/scan BTC`).
- `/trend <symbol>` - Check narrative & heat.
- `/risk <symbol>` - Risk assessment.
- `/stats` - View recent signals history.
- `/help` - Show help menu.

## 6. Project Structure

- `src/bot.py`: Telegram bot command handlers.
- `src/engines.py`: Signal generation and risk logic.
- `src/market_data.py`: Fetches market data (CCXT or Mock).
- `src/news_scanner.py`: Simulates news/sentiment analysis.
- `src/database.py`: SQLite database for users and signals.
- `src/config.py`: Configuration loader.
