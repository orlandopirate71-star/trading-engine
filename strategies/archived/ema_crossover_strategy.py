"""
EMA Crossover Strategy - Classic trend-following strategy using EMAs.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy_loader import BaseStrategy
from indicators import Indicators
from datetime import datetime
from typing import Optional
from models import TradeSignal


class EMACrossoverStrategy(BaseStrategy):
    """
    EMA Crossover with ADX filter:
    - Fast EMA crosses above slow EMA = Long
    - Fast EMA crosses below slow EMA = Short
    - ADX filter ensures we only trade in trending markets
    - ATR-based stop loss for volatility-adjusted risk
    """
    
    name = "EMACrossoverStrategy"
    
    def __init__(self, params: dict = None):
        super().__init__(params)
        
        self.indicators = {}  # Per-symbol indicators
        self.last_signal_time = {}  # Per-symbol cooldown
        self.prev_fast_ema = {}  # Per-symbol previous fast EMA
        self.prev_slow_ema = {}  # Per-symbol previous slow EMA
        
        # EMA periods
        self.fast_period = self.params.get("fast_period", 9)
        self.slow_period = self.params.get("slow_period", 21)
        
        # ADX filter (trend strength)
        self.adx_period = self.params.get("adx_period", 14)
        self.adx_threshold = self.params.get("adx_threshold", 25)  # Only trade when ADX > 25
        
        # ATR for stop loss
        self.atr_period = self.params.get("atr_period", 14)
        self.atr_multiplier = self.params.get("atr_multiplier", 2.0)
        
        # Risk/reward
        self.risk_reward = self.params.get("risk_reward", 2.0)
        
        # Cooldown
        self.cooldown_minutes = self.params.get("cooldown_minutes", 2)
    
    def on_tick(self, symbol: str, price: float, timestamp: datetime) -> Optional[TradeSignal]:
        # Initialize per-symbol state
        if symbol not in self.indicators:
            self.indicators[symbol] = Indicators(max_history=200)
            self.prev_fast_ema[symbol] = None
            self.prev_slow_ema[symbol] = None
        
        # Check cooldown
        if symbol in self.last_signal_time:
            time_since_signal = (timestamp - self.last_signal_time[symbol]).total_seconds() / 60
            if time_since_signal < self.cooldown_minutes:
                return None
        
        # Add price to indicators
        self.indicators[symbol].add(price)
        
        # Need enough data
        if self.indicators[symbol].count < self.slow_period + 10:
            return None
        
        # Calculate indicators
        fast_ema = self.indicators[symbol].ema(self.fast_period)
        slow_ema = self.indicators[symbol].ema(self.slow_period)
        adx = self.indicators[symbol].adx(self.adx_period)
        atr = self.indicators[symbol].atr(self.atr_period)
        
        if None in (fast_ema, slow_ema, atr):
            self.prev_fast_ema[symbol] = fast_ema
            self.prev_slow_ema[symbol] = slow_ema
            return None
        
        # Check for crossover
        bullish_cross = (self.prev_fast_ema[symbol] is not None and 
                        self.prev_slow_ema[symbol] is not None and
                        self.prev_fast_ema[symbol] <= self.prev_slow_ema[symbol] and 
                        fast_ema > slow_ema)
        
        bearish_cross = (self.prev_fast_ema[symbol] is not None and 
                        self.prev_slow_ema[symbol] is not None and
                        self.prev_fast_ema[symbol] >= self.prev_slow_ema[symbol] and 
                        fast_ema < slow_ema)
        
        # Update previous values
        self.prev_fast_ema[symbol] = fast_ema
        self.prev_slow_ema[symbol] = slow_ema
        
        # ADX filter - only trade in trending markets
        trending = adx is None or adx > self.adx_threshold
        
        # Calculate ATR-based stop loss
        stop_distance = atr * self.atr_multiplier
        
        # Long signal
        if bullish_cross and trending:
            self.last_signal_time[symbol] = timestamp
            stop_loss = price - stop_distance
            take_profit = price + (stop_distance * self.risk_reward)
            
            confidence = 0.6
            if adx and adx > 30:
                confidence += 0.1
            if adx and adx > 40:
                confidence += 0.1
            
            return self.create_signal(
                symbol=symbol,
                direction="LONG",
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=min(0.85, confidence),
                reason=f"EMA {self.fast_period}/{self.slow_period} bullish crossover" + 
                       (f", ADX={adx:.1f}" if adx else "")
            )
        
        # Short signal
        if bearish_cross and trending:
            self.last_signal_time[symbol] = timestamp
            stop_loss = price + stop_distance
            take_profit = price - (stop_distance * self.risk_reward)
            
            confidence = 0.6
            if adx and adx > 30:
                confidence += 0.1
            if adx and adx > 40:
                confidence += 0.1
            
            return self.create_signal(
                symbol=symbol,
                direction="SHORT",
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=min(0.85, confidence),
                reason=f"EMA {self.fast_period}/{self.slow_period} bearish crossover" +
                       (f", ADX={adx:.1f}" if adx else "")
            )
        
        return None
