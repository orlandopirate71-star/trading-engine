"""
RSI + MACD Strategy - Uses multiple indicators for confirmation.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy_loader import BaseStrategy
from indicators import Indicators
from datetime import datetime
from typing import Optional
from models import TradeSignal


class RSIMACDStrategy(BaseStrategy):
    """
    Combined RSI and MACD strategy:
    - RSI for overbought/oversold conditions
    - MACD for trend confirmation
    - Bollinger Bands for volatility context
    
    Long Entry:
    - RSI < 30 (oversold)
    - MACD histogram turning positive
    - Price near lower Bollinger Band
    
    Short Entry:
    - RSI > 70 (overbought)
    - MACD histogram turning negative
    - Price near upper Bollinger Band
    """
    
    name = "RSIMACDStrategy"
    
    def __init__(self, params: dict = None):
        super().__init__(params)
        
        # Per-symbol state
        self.indicators = {}
        self.last_signal_time = {}
        self.prev_macd_hist = {}
        
        # Parameters
        self.rsi_period = self.params.get("rsi_period", 14)
        self.rsi_oversold = self.params.get("rsi_oversold", 30)
        self.rsi_overbought = self.params.get("rsi_overbought", 70)
        self.bb_period = self.params.get("bb_period", 20)
        self.bb_std = self.params.get("bb_std", 2.0)
        
        # Risk management
        self.stop_loss_pct = self.params.get("stop_loss_pct", 0.02)
        self.take_profit_pct = self.params.get("take_profit_pct", 0.04)
        
        # Cooldown
        self.cooldown_minutes = self.params.get("cooldown_minutes", 3)
    
    def on_tick(self, symbol: str, price: float, timestamp: datetime) -> Optional[TradeSignal]:
        # Initialize per-symbol state
        if symbol not in self.indicators:
            self.indicators[symbol] = Indicators(max_history=200)
            self.prev_macd_hist[symbol] = None
        
        # Check cooldown
        if symbol in self.last_signal_time:
            time_since_signal = (timestamp - self.last_signal_time[symbol]).total_seconds() / 60
            if time_since_signal < self.cooldown_minutes:
                return None
        
        # Add price to indicator calculator
        self.indicators[symbol].add(price)
        
        # Need enough data
        if self.indicators[symbol].count < 50:
            return None
        
        # Calculate indicators
        rsi = self.indicators[symbol].rsi(self.rsi_period)
        macd_line, signal_line, macd_hist = self.indicators[symbol].macd()
        upper_bb, middle_bb, lower_bb = self.indicators[symbol].bollinger_bands(self.bb_period, self.bb_std)
        
        if None in (rsi, macd_hist, upper_bb):
            return None
        
        # Track MACD histogram direction
        macd_turning_up = self.prev_macd_hist[symbol] is not None and self.prev_macd_hist[symbol] < 0 and macd_hist > self.prev_macd_hist[symbol]
        macd_turning_down = self.prev_macd_hist[symbol] is not None and self.prev_macd_hist[symbol] > 0 and macd_hist < self.prev_macd_hist[symbol]
        self.prev_macd_hist[symbol] = macd_hist
        
        # Calculate distance from Bollinger Bands
        bb_range = upper_bb - lower_bb
        dist_from_lower = (price - lower_bb) / bb_range if bb_range > 0 else 0.5
        dist_from_upper = (upper_bb - price) / bb_range if bb_range > 0 else 0.5
        
        # Long signal: RSI oversold + MACD turning up + near lower BB
        if rsi < self.rsi_oversold and macd_turning_up and dist_from_lower < 0.3:
            self.last_signal_time[symbol] = timestamp
            confidence = 0.5 + (self.rsi_oversold - rsi) / 100 + (0.3 - dist_from_lower)
            
            return self.create_signal(
                symbol=symbol,
                direction="LONG",
                entry_price=price,
                stop_loss=price * (1 - self.stop_loss_pct),
                take_profit=price * (1 + self.take_profit_pct),
                confidence=min(0.9, confidence),
                reason=f"RSI oversold ({rsi:.1f}), MACD turning up, near lower BB"
            )
        
        # Short signal: RSI overbought + MACD turning down + near upper BB
        if rsi > self.rsi_overbought and macd_turning_down and dist_from_upper < 0.3:
            self.last_signal_time[symbol] = timestamp
            confidence = 0.5 + (rsi - self.rsi_overbought) / 100 + (0.3 - dist_from_upper)
            
            return self.create_signal(
                symbol=symbol,
                direction="SHORT",
                entry_price=price,
                stop_loss=price * (1 + self.stop_loss_pct),
                take_profit=price * (1 - self.take_profit_pct),
                confidence=min(0.9, confidence),
                reason=f"RSI overbought ({rsi:.1f}), MACD turning down, near upper BB"
            )
        
        return None
