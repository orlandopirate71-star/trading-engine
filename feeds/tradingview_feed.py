"""
TradingView Feed Integration

TradingView doesn't offer direct API access, but you can:
1. Use TradingView Alerts with webhooks to send signals/prices
2. This feed runs a webhook server to receive those alerts

Setup:
1. Run this feed (starts webhook server)
2. In TradingView, create an Alert
3. Set webhook URL to: http://YOUR_IP:5557/webhook
4. Set alert message to JSON format (see examples below)
"""
import json
from typing import List, Callable, Optional
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

from .base_feed import BaseFeed, Tick


class TradingViewHandler(BaseHTTPRequestHandler):
    """HTTP handler for TradingView webhooks."""
    
    feed: 'TradingViewFeed' = None
    
    def log_message(self, format, *args):
        pass
    
    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            
            # Try to parse as JSON
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                # Handle plain text alerts
                data = {"message": body}
            
            if self.feed:
                self.feed._process_alert(data)
            
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OK')
            
        except Exception as e:
            print(f"[TradingView] Webhook error: {e}")
            self.send_response(500)
            self.end_headers()
    
    def do_GET(self):
        """Health check."""
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(b'''
            <html><body>
            <h1>TradingView Webhook Server</h1>
            <p>Status: Running</p>
            <p>Send POST requests to /webhook</p>
            </body></html>
        ''')


class TradingViewFeed(BaseFeed):
    """
    TradingView webhook feed for receiving alerts.
    
    Can receive:
    1. Price updates (for data feed)
    2. Trade signals (for strategy signals)
    
    Alert Message Formats:
    
    Price Update:
    {"type": "price", "symbol": "{{ticker}}", "price": {{close}}, "bid": {{bid}}, "ask": {{ask}}}
    
    Trade Signal:
    {"type": "signal", "symbol": "{{ticker}}", "action": "buy", "price": {{close}}, "reason": "Your alert message"}
    """
    
    name = "TradingView"
    
    def __init__(
        self,
        symbols: List[str],
        host: str = "0.0.0.0",
        port: int = 5557,
        webhook_secret: str = None,
        on_tick: Callable[[Tick], None] = None,
        on_signal: Callable[[dict], None] = None
    ):
        super().__init__(symbols, on_tick)
        self.host = host
        self.port = port
        self.webhook_secret = webhook_secret
        self.on_signal = on_signal  # Callback for trade signals
        self.server: Optional[HTTPServer] = None
        self.alerts_received = 0
    
    def connect(self) -> bool:
        return True
    
    def disconnect(self):
        if self.server:
            self.server.shutdown()
    
    def _process_alert(self, data: dict):
        """Process incoming TradingView alert."""
        self.alerts_received += 1
        
        # Check webhook secret if configured
        if self.webhook_secret:
            if data.get("secret") != self.webhook_secret:
                print("[TradingView] Invalid webhook secret")
                return
        
        alert_type = data.get("type", "price")
        symbol = data.get("symbol", "").replace("/", "").upper()
        
        print(f"[TradingView] Alert #{self.alerts_received}: {alert_type} for {symbol}")
        
        if alert_type == "price":
            # Price update
            price = float(data.get("price", data.get("close", 0)))
            bid = float(data.get("bid", price))
            ask = float(data.get("ask", price))
            
            tick = Tick(
                symbol=symbol,
                price=price,
                bid=bid,
                ask=ask,
                source="TradingView"
            )
            self.emit_tick(tick)
            
        elif alert_type == "signal":
            # Trade signal from TradingView strategy/indicator
            signal = {
                "source": "TradingView",
                "symbol": symbol,
                "action": data.get("action", "").upper(),  # BUY, SELL
                "price": float(data.get("price", 0)),
                "stop_loss": data.get("stop_loss"),
                "take_profit": data.get("take_profit"),
                "reason": data.get("reason", data.get("message", "")),
                "timestamp": datetime.utcnow().isoformat()
            }
            
            if self.on_signal:
                self.on_signal(signal)
            
            # Also emit as tick for price tracking
            tick = Tick(
                symbol=symbol,
                price=signal["price"],
                source="TradingView"
            )
            self.emit_tick(tick)
    
    def _run(self):
        """Run webhook server."""
        TradingViewHandler.feed = self
        
        self.server = HTTPServer((self.host, self.port), TradingViewHandler)
        print(f"[TradingView] Webhook server running on http://{self.host}:{self.port}")
        print(f"[TradingView] Configure TradingView alerts to POST to this URL")
        
        while self.running:
            self.server.handle_request()
    
    @staticmethod
    def get_alert_templates() -> dict:
        """Get TradingView alert message templates."""
        return {
            "price_update": '''{
    "type": "price",
    "symbol": "{{ticker}}",
    "price": {{close}},
    "volume": {{volume}}
}''',
            "buy_signal": '''{
    "type": "signal",
    "symbol": "{{ticker}}",
    "action": "buy",
    "price": {{close}},
    "reason": "{{strategy.order.comment}}"
}''',
            "sell_signal": '''{
    "type": "signal",
    "symbol": "{{ticker}}",
    "action": "sell",
    "price": {{close}},
    "reason": "{{strategy.order.comment}}"
}''',
            "with_levels": '''{
    "type": "signal",
    "symbol": "{{ticker}}",
    "action": "buy",
    "price": {{close}},
    "stop_loss": {{plot_0}},
    "take_profit": {{plot_1}},
    "reason": "Strategy signal"
}'''
        }


class TradingViewBridge:
    """
    Bridge to integrate TradingView signals directly into the trading engine.
    Converts TradingView alerts into TradeSignals.
    """
    
    def __init__(self, trading_engine=None):
        self.trading_engine = trading_engine
        self.signals_received = []
    
    def on_signal(self, signal: dict):
        """Handle incoming TradingView signal."""
        print(f"[TVBridge] Signal: {signal['action']} {signal['symbol']} @ {signal['price']}")
        
        self.signals_received.append(signal)
        
        # If trading engine is connected, create a TradeSignal
        if self.trading_engine:
            from models import TradeSignal, TradeDirection
            
            direction = TradeDirection.LONG if signal["action"] == "BUY" else TradeDirection.SHORT
            
            trade_signal = TradeSignal(
                strategy_name="TradingView",
                symbol=signal["symbol"],
                direction=direction,
                entry_price=signal["price"],
                stop_loss=float(signal["stop_loss"]) if signal.get("stop_loss") else None,
                take_profit=float(signal["take_profit"]) if signal.get("take_profit") else None,
                confidence=0.8,  # TradingView signals get high confidence
                reason=signal.get("reason", "TradingView alert"),
                timestamp=datetime.utcnow()
            )
            
            # Process through the engine
            self.trading_engine._process_signal(trade_signal)
