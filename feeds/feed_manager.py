"""
Feed Manager - Manages multiple data feeds simultaneously.
"""
import json
from typing import Dict, List, Optional, Callable
from pathlib import Path
from datetime import datetime

from .base_feed import BaseFeed, Tick
from .binance_feed import BinanceFeed
from .finnhub_feed import FinnhubFeed
from .twelvedata_feed import TwelveDataFeed
from .polygon_feed import PolygonFeed
from .oanda_feed import OandaFeed
from .mt4_feed import MT4Feed, MT4SocketFeed
from .tradingview_feed import TradingViewFeed, TradingViewBridge

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from connections import redis_client


class FeedManager:
    """
    Manages multiple data feeds and aggregates ticks.
    Publishes all ticks to Redis for the trading engine.
    """
    
    def __init__(self, config_path: str = "feed_config.json"):
        self.feeds: Dict[str, BaseFeed] = {}
        self.config_path = Path(config_path)
        self.running = False
        self.tick_count = 0
        self.last_prices: Dict[str, Tick] = {}
        
        # Callbacks
        self.on_tick_callbacks: List[Callable[[Tick], None]] = []
    
    def _on_tick(self, tick: Tick):
        """Handle incoming tick from any feed."""
        self.tick_count += 1
        self.last_prices[tick.symbol] = tick
        
        # Publish to Redis
        redis_client.publish("ticks", json.dumps({
            "symbol": tick.symbol,
            "price": tick.price,
            "bid": tick.bid,
            "ask": tick.ask,
            "volume": tick.volume,
            "source": tick.source,
            "timestamp": tick.timestamp.isoformat() if tick.timestamp else None
        }))
        
        # Store latest price per symbol
        redis_client.hset("latest_prices", tick.symbol, tick.price)
        
        # Legacy support - single latest_price key
        redis_client.set("latest_price", tick.price)
        
        # Call registered callbacks
        for callback in self.on_tick_callbacks:
            try:
                callback(tick)
            except Exception as e:
                print(f"[FeedManager] Callback error: {e}")
    
    def add_binance(self, symbols: List[str]) -> 'FeedManager':
        """Add Binance feed for crypto pairs."""
        feed = BinanceFeed(symbols, on_tick=self._on_tick)
        self.feeds["binance"] = feed
        print(f"[FeedManager] Added Binance feed: {symbols}")
        return self
    
    def add_finnhub(self, symbols: List[str], api_key: str) -> 'FeedManager':
        """Add Finnhub feed for forex/stocks/crypto."""
        feed = FinnhubFeed(symbols, api_key, on_tick=self._on_tick)
        self.feeds["finnhub"] = feed
        print(f"[FeedManager] Added Finnhub feed: {symbols}")
        return self
    
    def add_twelvedata(self, symbols: List[str], api_key: str, poll_interval: float = 5.0) -> 'FeedManager':
        """Add Twelve Data feed for forex/stocks/crypto."""
        feed = TwelveDataFeed(symbols, api_key, on_tick=self._on_tick, poll_interval=poll_interval)
        self.feeds["twelvedata"] = feed
        print(f"[FeedManager] Added TwelveData feed: {symbols}")
        return self
    
    def add_polygon(self, symbols: List[str], api_key: str) -> 'FeedManager':
        """Add Polygon feed for forex/stocks/crypto."""
        feed = PolygonFeed(symbols, api_key, on_tick=self._on_tick)
        self.feeds["polygon"] = feed
        print(f"[FeedManager] Added Polygon feed: {symbols}")
        return self
    
    def add_oanda(self, symbols: List[str], account_id: str, api_token: str, practice: bool = True) -> 'FeedManager':
        """Add OANDA feed for forex."""
        feed = OandaFeed(symbols, account_id, api_token, practice, on_tick=self._on_tick)
        self.feeds["oanda"] = feed
        print(f"[FeedManager] Added OANDA feed: {symbols}")
        return self
    
    def add_mt4(self, symbols: List[str], port: int = 5555) -> 'FeedManager':
        """Add MT4 feed (requires EA running in MT4)."""
        feed = MT4Feed(symbols, port=port, on_tick=self._on_tick)
        self.feeds["mt4"] = feed
        print(f"[FeedManager] Added MT4 feed on port {port}")
        return self
    
    def add_mt4_socket(self, symbols: List[str], port: int = 5556) -> 'FeedManager':
        """Add MT4 socket feed (faster, requires socket EA)."""
        feed = MT4SocketFeed(symbols, port=port, on_tick=self._on_tick)
        self.feeds["mt4_socket"] = feed
        print(f"[FeedManager] Added MT4 Socket feed on port {port}")
        return self
    
    def add_tradingview(self, symbols: List[str], port: int = 5557, webhook_secret: str = None, on_signal: Callable = None) -> 'FeedManager':
        """Add TradingView webhook feed."""
        feed = TradingViewFeed(symbols, port=port, webhook_secret=webhook_secret, on_tick=self._on_tick, on_signal=on_signal)
        self.feeds["tradingview"] = feed
        print(f"[FeedManager] Added TradingView webhook on port {port}")
        return self
    
    def add_callback(self, callback: Callable[[Tick], None]):
        """Add a callback to be called on each tick."""
        self.on_tick_callbacks.append(callback)
    
    def load_config(self) -> 'FeedManager':
        """Load feed configuration from JSON file."""
        if not self.config_path.exists():
            print(f"[FeedManager] No config file found at {self.config_path}")
            return self
        
        with open(self.config_path) as f:
            config = json.load(f)
        
        for feed_config in config.get("feeds", []):
            feed_type = feed_config.get("type", "").lower()
            symbols = feed_config.get("symbols", [])
            enabled = feed_config.get("enabled", True)
            
            if not enabled:
                continue
            
            if feed_type == "binance":
                self.add_binance(symbols)
            
            elif feed_type == "finnhub":
                api_key = feed_config.get("api_key")
                if api_key:
                    self.add_finnhub(symbols, api_key)
            
            elif feed_type == "twelvedata":
                api_key = feed_config.get("api_key")
                poll_interval = feed_config.get("poll_interval", 5.0)
                if api_key:
                    self.add_twelvedata(symbols, api_key, poll_interval)
            
            elif feed_type == "polygon":
                api_key = feed_config.get("api_key")
                if api_key:
                    self.add_polygon(symbols, api_key)
            
            elif feed_type == "oanda":
                account_id = feed_config.get("account_id")
                api_token = feed_config.get("api_token")
                practice = feed_config.get("practice", True)
                if account_id and api_token:
                    self.add_oanda(symbols, account_id, api_token, practice)
            
            elif feed_type == "mt4":
                port = feed_config.get("port", 5555)
                self.add_mt4(symbols, port)
            
            elif feed_type == "mt4_socket":
                port = feed_config.get("port", 5556)
                self.add_mt4_socket(symbols, port)
            
            elif feed_type == "tradingview":
                port = feed_config.get("port", 5557)
                secret = feed_config.get("webhook_secret")
                self.add_tradingview(symbols, port, secret)
        
        return self
    
    def start(self):
        """Start all feeds."""
        if not self.feeds:
            print("[FeedManager] No feeds configured!")
            return
        
        self.running = True
        print(f"[FeedManager] Starting {len(self.feeds)} feeds...")
        
        for name, feed in self.feeds.items():
            feed.start()
        
        print("[FeedManager] All feeds started")
    
    def stop(self):
        """Stop all feeds."""
        self.running = False
        print("[FeedManager] Stopping all feeds...")
        
        for name, feed in self.feeds.items():
            feed.stop()
        
        print("[FeedManager] All feeds stopped")
    
    def get_status(self) -> dict:
        """Get status of all feeds."""
        return {
            "running": self.running,
            "tick_count": self.tick_count,
            "feeds": {
                name: {
                    "name": feed.name,
                    "symbols": feed.symbols,
                    "running": feed.running
                }
                for name, feed in self.feeds.items()
            },
            "last_prices": {
                symbol: {
                    "price": tick.price,
                    "source": tick.source,
                    "timestamp": tick.timestamp.isoformat() if tick.timestamp else None
                }
                for symbol, tick in self.last_prices.items()
            }
        }
    
    def get_price(self, symbol: str) -> Optional[float]:
        """Get latest price for a symbol."""
        tick = self.last_prices.get(symbol)
        return tick.price if tick else None


# Singleton
_manager: Optional[FeedManager] = None

def get_feed_manager(config_path: str = "feed_config.json") -> FeedManager:
    global _manager
    if _manager is None:
        _manager = FeedManager(config_path)
    return _manager
