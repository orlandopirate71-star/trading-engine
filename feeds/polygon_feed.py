"""
Polygon.io WebSocket feed - Forex, Stocks, Crypto.
Free tier: 5 API calls/minute, delayed data.
Get free API key at: https://polygon.io/
"""
import json
import websocket
from typing import List, Callable
from datetime import datetime

from .base_feed import BaseFeed, Tick


class PolygonFeed(BaseFeed):
    """
    Polygon.io WebSocket feed.
    
    Symbols format:
    - Forex: C:EURUSD, C:GBPUSD
    - Crypto: X:BTCUSD, X:ETHUSD
    - Stocks: AAPL, MSFT
    """
    
    name = "Polygon"
    
    def __init__(self, symbols: List[str], api_key: str, on_tick: Callable[[Tick], None] = None):
        super().__init__(symbols, on_tick)
        self.api_key = api_key
        self.ws = None
        # Use different endpoints based on asset type
        self.forex_url = "wss://socket.polygon.io/forex"
        self.crypto_url = "wss://socket.polygon.io/crypto"
        self.stocks_url = "wss://socket.polygon.io/stocks"
    
    def connect(self) -> bool:
        return True
    
    def disconnect(self):
        if self.ws:
            self.ws.close()
    
    def _categorize_symbols(self):
        """Categorize symbols by asset type."""
        forex = [s for s in self.symbols if s.startswith("C:")]
        crypto = [s for s in self.symbols if s.startswith("X:")]
        stocks = [s for s in self.symbols if not s.startswith(("C:", "X:"))]
        return {"forex": forex, "crypto": crypto, "stocks": stocks}
    
    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            
            for item in data if isinstance(data, list) else [data]:
                ev = item.get("ev")
                
                # Currency/Forex aggregate
                if ev in ["CA", "XA"]:  # Forex or Crypto aggregate
                    symbol = item.get("pair", "")
                    price = float(item.get("c", 0))  # Close price
                    volume = float(item.get("v", 0))
                    
                    tick = Tick(
                        symbol=symbol.replace("/", ""),
                        price=price,
                        volume=volume,
                        source=self.name
                    )
                    self.emit_tick(tick)
                
                # Quote update
                elif ev == "C":
                    symbol = item.get("p", "")
                    bid = float(item.get("b", 0))
                    ask = float(item.get("a", 0))
                    price = (bid + ask) / 2
                    
                    tick = Tick(
                        symbol=symbol,
                        price=price,
                        bid=bid,
                        ask=ask,
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
        # Authenticate
        ws.send(json.dumps({"action": "auth", "params": self.api_key}))
        
        # Subscribe to symbols
        categories = self._categorize_symbols()
        
        for symbol in self.symbols:
            ws.send(json.dumps({
                "action": "subscribe",
                "params": f"C.{symbol}" if symbol.startswith("C:") else symbol
            }))
        
        print(f"[{self.name}] Subscribed to {len(self.symbols)} symbols")
    
    def _run(self):
        # Determine which endpoint to use based on symbols
        categories = self._categorize_symbols()
        
        if categories["forex"]:
            url = self.forex_url
        elif categories["crypto"]:
            url = self.crypto_url
        else:
            url = self.stocks_url
        
        while self.running:
            try:
                self.ws = websocket.WebSocketApp(
                    url,
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
