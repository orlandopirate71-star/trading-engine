"""
Breakout Strategy - Trades breakouts from price ranges.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy_loader import BaseStrategy
from datetime import datetime
from typing import Optional
from models import TradeSignal


class BreakoutStrategy(BaseStrategy):
    """
    Breakout strategy that generates signals when price breaks out of a range.
    - Tracks high/low over a lookback period
    - Signals on breakout with volume confirmation (simulated)
    """
    name = "BreakoutStrategy"
    symbols = None  # Uses all active symbols from feed_config.json
    
    def __init__(self, params: dict = None):
        super().__init__(params)
        self.prices = {}  # Dict of symbol -> price list
        self.lookback = self.params.get("lookback", 50)
        self.breakout_threshold = self.params.get("breakout_threshold", 0.002)  # 0.2%
        self.stop_loss_pct = self.params.get("stop_loss_pct", 0.015)  # 1.5%
        self.take_profit_pct = self.params.get("take_profit_pct", 0.03)  # 3%
        self.cooldown_ticks = self.params.get("cooldown_ticks", 200)
        self.ticks_since_signal = {}  # Dict of symbol -> ticks since last signal
    
    def on_tick(self, symbol: str, price: float, timestamp: datetime) -> Optional[TradeSignal]:
        # Initialize per-symbol tracking
        if symbol not in self.prices:
            self.prices[symbol] = []
            self.ticks_since_signal[symbol] = self.cooldown_ticks
        
        self.prices[symbol].append(price)
        self.ticks_since_signal[symbol] += 1
        
        # Keep only needed history
        if len(self.prices[symbol]) > self.lookback + 10:
            self.prices[symbol].pop(0)
        
        # Need enough data
        if len(self.prices[symbol]) < self.lookback:
            return None
        
        # Cooldown between signals
        if self.ticks_since_signal[symbol] < self.cooldown_ticks:
            return None
        
        # Calculate range (excluding current price)
        range_prices = self.prices[symbol][-self.lookback:-1]
        range_high = max(range_prices)
        range_low = min(range_prices)
        range_size = range_high - range_low
        
        # Skip if range is too tight (consolidation)
        if range_size / price < 0.005:  # Less than 0.5% range
            return None
        
        # Breakout above resistance
        if price > range_high * (1 + self.breakout_threshold):
            self.ticks_since_signal[symbol] = 0
            return self.create_signal(
                symbol=symbol,
                direction="LONG",
                entry_price=price,
                stop_loss=range_high - (range_size * 0.5),  # Stop below breakout level
                take_profit=price + (range_size * 1.5),  # Target 1.5x the range
                confidence=0.65,
                reason=f"Bullish breakout above {range_high:.2f} resistance"
            )
        
        # Breakout below support
        if price < range_low * (1 - self.breakout_threshold):
            self.ticks_since_signal[symbol] = 0
            return self.create_signal(
                symbol=symbol,
                direction="SHORT",
                entry_price=price,
                stop_loss=range_low + (range_size * 0.5),  # Stop above breakout level
                take_profit=price - (range_size * 1.5),  # Target 1.5x the range
                confidence=0.65,
                reason=f"Bearish breakout below {range_low:.2f} support"
            )
        
        return None
