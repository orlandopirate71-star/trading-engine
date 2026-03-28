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
        self.prices = []
        self.ma_period = self.params.get("ma_period", 20)
        self.momentum_threshold = self.params.get("momentum_threshold", 0.005)  # 0.5%
        self.stop_loss_pct = self.params.get("stop_loss_pct", 0.02)  # 2%
        self.take_profit_pct = self.params.get("take_profit_pct", 0.04)  # 4%
        self.cooldown_ticks = self.params.get("cooldown_ticks", 100)
        self.ticks_since_signal = self.cooldown_ticks
    
    def on_tick(self, symbol: str, price: float, timestamp: datetime) -> Optional[TradeSignal]:
        self.prices.append(price)
        self.ticks_since_signal += 1
        
        # Keep only needed history
        if len(self.prices) > self.ma_period + 10:
            self.prices.pop(0)
        
        # Need enough data
        if len(self.prices) < self.ma_period + 1:
            return None
        
        # Cooldown between signals
        if self.ticks_since_signal < self.cooldown_ticks:
            return None
        
        # Calculate moving average
        ma = sum(self.prices[-self.ma_period:]) / self.ma_period
        prev_price = self.prices[-2]
        
        # Calculate momentum
        momentum = (price - prev_price) / prev_price
        
        # Long signal: price crosses above MA with positive momentum
        if prev_price <= ma and price > ma and momentum > self.momentum_threshold:
            self.ticks_since_signal = 0
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
            self.ticks_since_signal = 0
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
