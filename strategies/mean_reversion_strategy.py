"""
Mean Reversion Strategy - Trades when price deviates significantly from average.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy_loader import BaseStrategy
from datetime import datetime
from typing import Optional
from models import TradeSignal
import math


class MeanReversionStrategy(BaseStrategy):
    """
    Mean reversion strategy that generates signals when price is oversold/overbought.
    Uses standard deviation bands similar to Bollinger Bands.
    """
    name = "MeanReversionStrategy"
    
    def __init__(self, params: dict = None):
        super().__init__(params)
        self.prices = []
        self.period = self.params.get("period", 30)
        self.std_multiplier = self.params.get("std_multiplier", 2.0)
        self.stop_loss_pct = self.params.get("stop_loss_pct", 0.025)  # 2.5%
        self.take_profit_pct = self.params.get("take_profit_pct", 0.02)  # 2% (mean reversion target)
        self.cooldown_ticks = self.params.get("cooldown_ticks", 150)
        self.ticks_since_signal = self.cooldown_ticks
    
    def _calculate_std(self, prices: list) -> float:
        """Calculate standard deviation."""
        if len(prices) < 2:
            return 0
        mean = sum(prices) / len(prices)
        variance = sum((p - mean) ** 2 for p in prices) / len(prices)
        return math.sqrt(variance)
    
    def on_tick(self, symbol: str, price: float, timestamp: datetime) -> Optional[TradeSignal]:
        self.prices.append(price)
        self.ticks_since_signal += 1
        
        # Keep only needed history
        if len(self.prices) > self.period + 10:
            self.prices.pop(0)
        
        # Need enough data
        if len(self.prices) < self.period:
            return None
        
        # Cooldown between signals
        if self.ticks_since_signal < self.cooldown_ticks:
            return None
        
        # Calculate bands
        period_prices = self.prices[-self.period:]
        mean = sum(period_prices) / len(period_prices)
        std = self._calculate_std(period_prices)
        
        if std == 0:
            return None
        
        upper_band = mean + (std * self.std_multiplier)
        lower_band = mean - (std * self.std_multiplier)
        
        # Calculate z-score
        z_score = (price - mean) / std
        
        # Oversold - price below lower band (buy signal)
        if price < lower_band:
            self.ticks_since_signal = 0
            return self.create_signal(
                symbol=symbol,
                direction="LONG",
                entry_price=price,
                stop_loss=price * (1 - self.stop_loss_pct),
                take_profit=mean,  # Target the mean
                confidence=min(0.85, 0.5 + abs(z_score) * 0.1),
                reason=f"Oversold: price {z_score:.2f} std below mean, expecting reversion to {mean:.2f}"
            )
        
        # Overbought - price above upper band (sell signal)
        if price > upper_band:
            self.ticks_since_signal = 0
            return self.create_signal(
                symbol=symbol,
                direction="SHORT",
                entry_price=price,
                stop_loss=price * (1 + self.stop_loss_pct),
                take_profit=mean,  # Target the mean
                confidence=min(0.85, 0.5 + abs(z_score) * 0.1),
                reason=f"Overbought: price {z_score:.2f} std above mean, expecting reversion to {mean:.2f}"
            )
        
        return None
