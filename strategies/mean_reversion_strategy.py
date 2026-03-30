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
        self.last_signal_time = {}  # Per-symbol last signal timestamp
        self.period = self.params.get("period", 30)
        self.std_multiplier = self.params.get("std_multiplier", 1.5)  # Tighter bands for earlier entry
        self.stop_loss_pct = self.params.get("stop_loss_pct", 0.005)  # 0.5% (very tight for mean reversion)
        self.take_profit_pct = self.params.get("take_profit_pct", 0.01)  # 1% (conservative mean reversion)
        self.cooldown_minutes = self.params.get("cooldown_minutes", 5)  # 5 minute cooldown
        self.min_risk_reward = self.params.get("min_risk_reward", 1.2)  # Minimum 1.2:1 R:R (relaxed)
        self.timeframe = "M1"  # Use M1 candles
    
    def _calculate_std(self, prices: list) -> float:
        """Calculate standard deviation."""
        if len(prices) < 2:
            return 0
        mean = sum(prices) / len(prices)
        variance = sum((p - mean) ** 2 for p in prices) / len(prices)
        return math.sqrt(variance)
    
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
            candles = candle_store.get_recent_candles(symbol, self.timeframe, count=self.period)
            
            if not candles or len(candles) < self.period:
                return None
            
            # Extract closing prices (handle both dict and object format)
            period_prices = []
            for c in candles:
                if isinstance(c, dict):
                    period_prices.append(c['close'])
                else:
                    period_prices.append(c.close)
        except Exception as e:
            print(f"[MeanReversion] Error fetching candles for {symbol}: {e}")
            return None
        
        # Calculate bands
        mean = sum(period_prices) / len(period_prices)
        std = self._calculate_std(period_prices)
        
        if std == 0:
            return None
        
        upper_band = mean + (std * self.std_multiplier)
        lower_band = mean - (std * self.std_multiplier)
        
        # Calculate z-score
        z_score = (price - mean) / std
        
        # Oversold - price below lower band (buy signal)
        if price < lower_band and z_score < -self.std_multiplier:
            stop_loss = price * (1 - self.stop_loss_pct)
            take_profit = mean  # Target the mean
            
            # Validate: TP must be above entry for longs
            if take_profit <= price:
                return None
            
            # Check risk/reward ratio
            risk = price - stop_loss
            reward = take_profit - price
            if risk <= 0 or reward / risk < self.min_risk_reward:
                return None
            
            self.last_signal_time[symbol] = timestamp
            return self.create_signal(
                symbol=symbol,
                direction="LONG",
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=min(0.85, 0.5 + abs(z_score) * 0.1),
                reason=f"Oversold: price {z_score:.2f} std below mean at {lower_band:.2f}, expecting reversion to {mean:.2f}, R:R={reward/risk:.2f}"
            )
        
        # Overbought - price above upper band (sell signal)
        if price > upper_band and z_score > self.std_multiplier:
            stop_loss = price * (1 + self.stop_loss_pct)
            take_profit = mean  # Target the mean
            
            # Debug: Log values
            print(f"[MeanReversion] SHORT signal: price={price:.2f}, mean={mean:.2f}, upper={upper_band:.2f}, SL={stop_loss:.2f}, TP={take_profit:.2f}")
            
            # Validate: TP must be below entry for shorts
            if take_profit >= price:
                print(f"[MeanReversion] Rejected: TP ({take_profit:.2f}) >= price ({price:.2f})")
                return None
            
            # Check risk/reward ratio
            risk = stop_loss - price
            reward = price - take_profit
            if risk <= 0 or reward / risk < self.min_risk_reward:
                return None
            
            self.last_signal_time[symbol] = timestamp
            return self.create_signal(
                symbol=symbol,
                direction="SHORT",
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=min(0.85, 0.5 + abs(z_score) * 0.1),
                reason=f"Overbought: price {z_score:.2f} std above mean at {upper_band:.2f}, expecting reversion to {mean:.2f}, R:R={reward/risk:.2f}"
            )
        
        return None
