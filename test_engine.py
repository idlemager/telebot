from src.engines import SignalEngine
import logging
import traceback

# Mute logs for test
logging.basicConfig(level=logging.INFO)

def test():
    try:
        print("Initializing Signal Engine...")
        engine = SignalEngine()
        print("Testing Signal Engine...")
        
        # Test with a few symbols
        symbols = ['BTC/USDT', 'ETH/USDT', 'DOGE/USDT']
        
        for symbol in symbols:
            print(f"\nAnalyzing {symbol}...")
            signal = engine.analyze_symbol(symbol)
            if signal:
                print(f"Result: {signal['symbol']} | Direction: {signal['direction']} | Risk: {signal['risk_level']}")
                print(f"Heat: {signal['heat_score']} | Volume Score: {signal['volume_score']}")
                print(f"Narrative: {signal['narrative']}")
            else:
                print("Failed to analyze.")
    except Exception:
        traceback.print_exc()

if __name__ == "__main__":
    test()
