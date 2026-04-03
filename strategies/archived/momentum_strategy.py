"""
Momentum Strategy - Trades based on price momentum and moving averages.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy_loader import BaseStrategy
from datetime import datetime
from typing import Optional
from models import TradeSignal


class MomentumStrategy(BaseStrategy):
    """
    Simple momentum strategy that generates signals based on:
    - Price crossing above/below a moving average
    - Minimum momentum threshold
    """
    name = "MomentumStrategy"
    
    def __init__(self, params: dict = None):
        super().__init__(params)
        self.last_signal_time = {}  # Per-symbol cooldown
        self.ma_period = self.params.get("ma_period", 20)
        self.momentum_threshold = self.params.get("momentum_threshold", 0.005)  # 0.5%
        self.stop_loss_pct = self.params.get("stop_loss_pct", 0.02)  # 2%
        self.take_profit_pct = self.params.get("take_profit_pct", 0.04)  # 4%
        self.cooldown_minutes = self.params.get("cooldown_minutes", 3)
        self.timeframe = "M1"
    
    def on_tick(self, symbol: str, price: float, timestamp: datetime) -> Optional[TradeSignal]:
        # Check cooldown
        if symbol in self.last_signal_time:
            time_since_signal = (timestamp - self.last_signal_time[symbol]).total_seconds() / 60
            if time_since_signal < self.cooldown_minutes:
                return None
        
        # Get recent candles from database
        try:
            from candle_store import get_candle_store
            candle_store = get_candle_store()
            candles = candle_store.get_recent_candles(symbol, self.timeframe, count=self.ma_period + 1)
            
            if not candles or len(candles) < self.ma_period + 1:
                return None
            
            # Extract closing prices
            prices = [c['close'] if isinstance(c, dict) else c.close for c in candles]
        except Exception as e:
            return None
        
        # Calculate moving average
        ma = sum(prices[-self.ma_period:]) / self.ma_period
        prev_price = prices[-2]
        
        # Calculate momentum
        momentum = (price - prev_price) / prev_price
        
        # Long signal: price crosses above MA with positive momentum
        if prev_price <= ma and price > ma and momentum > self.momentum_threshold:
            self.last_signal_time[symbol] = timestamp
            return self.create_signal(
                symbol=symbol,
                direction="LONG",
                entry_price=price,
                stop_loss=price * (1 - self.stop_loss_pct),
                take_profit=price * (1 + self.take_profit_pct),
                confidence=min(0.9, 0.5 + abs(momentum) * 10),
                reason=f"Price crossed above {self.ma_period}-MA with {momentum*100:.2f}% momentum"
            )
        
        # Short signal: price crosses below MA with negative momentum
        if prev_price >= ma and price < ma and momentum < -self.momentum_threshold:
            self.last_signal_time[symbol] = timestamp
            return self.create_signal(
                symbol=symbol,
                direction="SHORT",
                entry_price=price,
                stop_loss=price * (1 + self.stop_loss_pct),
                take_profit=price * (1 - self.take_profit_pct),
                confidence=min(0.9, 0.5 + abs(momentum) * 10),
                reason=f"Price crossed below {self.ma_period}-MA with {momentum*100:.2f}% momentum"
            )
        
        return None
