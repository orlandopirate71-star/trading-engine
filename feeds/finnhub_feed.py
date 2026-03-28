"""
Finnhub WebSocket feed - Forex, Stocks, Crypto.
Free tier: 60 API calls/minute, WebSocket available.
Get free API key at: https://finnhub.io/
"""
import json
import websocket
from typing import List, Callable
from datetime import datetime

from .base_feed import BaseFeed, Tick


class FinnhubFeed(BaseFeed):
    """
    Finnhub WebSocket feed for forex, stocks, and crypto.
    
    Symbols format:
    - Forex: OANDA:EUR_USD, OANDA:GBP_USD
    - Crypto: BINANCE:BTCUSDT
    - Stocks: AAPL, MSFT
    """
    
    name = "Finnhub"
    
    def __init__(self, symbols: List[str], api_key: str, on_tick: Callable[[Tick], None] = None):
        super().__init__(symbols, on_tick)
        self.api_key = api_key
        self.ws = None
        self.base_url = f"wss://ws.finnhub.io?token={api_key}"
    
    def connect(self) -> bool:
        return True
    
    def disconnect(self):
        if self.ws:
            self.ws.close()
    
    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            
            if data.get("type") == "trade":
                for trade in data.get("data", []):
                    symbol = trade.get("s", "")
                    price = float(trade.get("p", 0))
                    volume = float(trade.get("v", 0))
                    timestamp = datetime.fromtimestamp(trade.get("t", 0) / 1000)
                    
                    # Normalize symbol (remove exchange prefix for display)
                    display_symbol = symbol.split(":")[-1] if ":" in symbol else symbol
                    
                    tick = Tick(
                        symbol=display_symbol,
                        price=price,
                        volume=volume,
                        timestamp=timestamp,
                        source=self.name
                    )
                    
                    self.emit_tick(tick)
                    
        except Exception as e:
            print(f"[{self.name}] Parse error: {e}")
    
    def _on_error(self, ws, error):
        print(f"[{self.name}] Error: {error}")
    
    def _on_close(self, ws, close_status, close_msg):
        print(f"[{self.name}] Connection closed")
    
    def _on_open(self, ws):
        print(f"[{self.name}] Connected - subscribing to {len(self.symbols)} symbols")
        # Subscribe to each symbol
        for symbol in self.symbols:
            ws.send(json.dumps({"type": "subscribe", "symbol": symbol}))
    
    def _run(self):
        while self.running:
            try:
                self.ws = websocket.WebSocketApp(
                    self.base_url,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                    on_open=self._on_open
                )
                
                self.ws.run_forever()
                
            except Exception as e:
                print(f"[{self.name}] Reconnecting: {e}")
                if self.running:
                    import time
                    time.sleep(5)
