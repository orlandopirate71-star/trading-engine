"""
Binance WebSocket feed - Crypto pairs.
Free, no API key required for public data.
"""
import json
import websocket
from typing import List, Callable
from datetime import datetime

from .base_feed import BaseFeed, Tick


class BinanceFeed(BaseFeed):
    """
    Binance WebSocket feed for crypto pairs.
    Supports multiple symbols simultaneously.
    
    Symbols format: BTCUSDT, ETHUSDT, etc.
    """
    
    name = "Binance"
    
    def __init__(self, symbols: List[str], on_tick: Callable[[Tick], None] = None):
        super().__init__(symbols, on_tick)
        self.ws = None
        self.base_url = "wss://stream.binance.com:9443/ws"
    
    def connect(self) -> bool:
        return True  # Connection happens in _run
    
    def disconnect(self):
        if self.ws:
            self.ws.close()
    
    def _build_url(self) -> str:
        """Build WebSocket URL for multiple symbols."""
        streams = [f"{s.lower()}@ticker" for s in self.symbols]
        return f"{self.base_url}/{'/'.join(streams)}"
    
    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            
            # Handle combined stream format
            if "stream" in data:
                data = data["data"]
            
            symbol = data.get("s", "").upper()
            price = float(data.get("c", 0))  # Current price
            bid = float(data.get("b", 0))    # Best bid
            ask = float(data.get("a", 0))    # Best ask
            volume = float(data.get("v", 0)) # 24h volume
            
            tick = Tick(
                symbol=symbol,
                price=price,
                bid=bid,
                ask=ask,
                volume=volume,
                source=self.name
            )
            
            self.emit_tick(tick)
            
        except Exception as e:
            print(f"[{self.name}] Parse error: {e}")
    
    def _on_error(self, ws, error):
        print(f"[{self.name}] Error: {error}")
    
    def _on_close(self, ws, close_status, close_msg):
        print(f"[{self.name}] Connection closed: {close_status}")
    
    def _on_open(self, ws):
        print(f"[{self.name}] Connected - streaming {len(self.symbols)} symbols")
    
    def _run(self):
        """Main WebSocket loop with auto-reconnect."""
        while self.running:
            try:
                # For multiple symbols, use combined streams
                if len(self.symbols) > 1:
                    streams = [f"{s.lower()}@ticker" for s in self.symbols]
                    url = f"wss://stream.binance.com:9443/stream?streams={'/'.join(streams)}"
                else:
                    url = f"wss://stream.binance.com:9443/ws/{self.symbols[0].lower()}@ticker"
                
                self.ws = websocket.WebSocketApp(
                    url,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                    on_open=self._on_open
                )
                
                self.ws.run_forever()
                
            except Exception as e:
                print(f"[{self.name}] Reconnecting after error: {e}")
                if self.running:
                    import time
                    time.sleep(5)
