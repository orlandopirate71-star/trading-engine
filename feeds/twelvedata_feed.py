"""
Twelve Data feed - Forex, Stocks, Crypto.
Free tier: 800 API calls/day, 8 symbols max.
Get free API key at: https://twelvedata.com/
"""
import json
import requests
import time
from typing import List, Callable
from datetime import datetime
import threading

from .base_feed import BaseFeed, Tick


class TwelveDataFeed(BaseFeed):
    """
    Twelve Data REST API feed (polling).
    WebSocket requires paid plan, so we poll.
    
    Symbols format:
    - Forex: EUR/USD, GBP/USD, USD/JPY
    - Crypto: BTC/USD, ETH/USD
    - Stocks: AAPL, MSFT
    """
    
    name = "TwelveData"
    
    def __init__(self, symbols: List[str], api_key: str, on_tick: Callable[[Tick], None] = None, poll_interval: float = 5.0):
        super().__init__(symbols, on_tick)
        self.api_key = api_key
        self.poll_interval = poll_interval
        self.base_url = "https://api.twelvedata.com"
    
    def connect(self) -> bool:
        # Test connection
        try:
            response = requests.get(
                f"{self.base_url}/time_series",
                params={
                    "symbol": self.symbols[0],
                    "interval": "1min",
                    "outputsize": 1,
                    "apikey": self.api_key
                },
                timeout=10
            )
            return response.status_code == 200
        except:
            return False
    
    def disconnect(self):
        pass
    
    def _fetch_prices(self):
        """Fetch current prices for all symbols."""
        try:
            # Batch request for multiple symbols
            symbols_str = ",".join(self.symbols)
            
            response = requests.get(
                f"{self.base_url}/price",
                params={
                    "symbol": symbols_str,
                    "apikey": self.api_key
                },
                timeout=10
            )
            
            if response.status_code != 200:
                print(f"[{self.name}] API error: {response.status_code}")
                return
            
            data = response.json()
            
            # Handle single vs multiple symbols response format
            if len(self.symbols) == 1:
                data = {self.symbols[0]: data}
            
            for symbol, price_data in data.items():
                if "price" in price_data:
                    tick = Tick(
                        symbol=symbol.replace("/", ""),  # EUR/USD -> EURUSD
                        price=float(price_data["price"]),
                        source=self.name
                    )
                    self.emit_tick(tick)
                    
        except Exception as e:
            print(f"[{self.name}] Fetch error: {e}")
    
    def _run(self):
        print(f"[{self.name}] Polling every {self.poll_interval}s")
        
        while self.running:
            self._fetch_prices()
            time.sleep(self.poll_interval)
