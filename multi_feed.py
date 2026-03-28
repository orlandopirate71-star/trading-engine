#!/usr/bin/env python3
"""
Multi-Feed Data Runner
Runs multiple data feeds simultaneously based on feed_config.json
"""
import signal
import sys
import time

from feeds.feed_manager import get_feed_manager


def main():
    print("=" * 50)
    print("  Multi-Feed Data Runner")
    print("=" * 50)
    
    # Load configuration and create feeds
    manager = get_feed_manager("feed_config.json")
    manager.load_config()
    
    # If no feeds configured from file, add default Binance
    if not manager.feeds:
        print("\nNo feeds in config, using default Binance feed...")
        manager.add_binance(["BTCUSDT", "ETHUSDT"])
    
    # Handle shutdown
    def shutdown(sig, frame):
        print("\n\nShutting down feeds...")
        manager.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    
    # Start all feeds
    manager.start()
    
    # Print status periodically
    print("\nFeeds running. Press Ctrl+C to stop.\n")
    
    last_count = 0
    while manager.running:
        time.sleep(10)
        
        status = manager.get_status()
        new_ticks = status["tick_count"] - last_count
        last_count = status["tick_count"]
        
        print(f"[Status] {new_ticks} ticks in last 10s | Total: {status['tick_count']} | Symbols: {len(status['last_prices'])}")
        
        # Show latest prices
        for symbol, data in list(status["last_prices"].items())[:5]:
            print(f"  {symbol}: ${data['price']:.2f} ({data['source']})")


if __name__ == "__main__":
    main()
