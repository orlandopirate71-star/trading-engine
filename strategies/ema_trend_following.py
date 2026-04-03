"""
EMA Trend Following Strategy - Rides strong trends using multiple EMA crossovers.
Designed for trending forex markets with clear directional bias.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy_loader import BaseStrategy
from indicators import Indicators
from datetime import datetime
from typing import Optional
from models import TradeSignal


class EMATrendFollowingStrategy(BaseStrategy):
    """
    Triple EMA trend following strategy:
    - Uses 9, 21, and 50 EMA for trend identification
    - Enters on pullbacks to the fast EMA in trending markets
    - Confirms with MACD and ADX
    - Trails stops using the 21 EMA
    
    Long Entry:
    - 9 EMA > 21 EMA > 50 EMA (bullish alignment)
    - Price pulls back to 9 EMA
    - MACD histogram positive
    - ADX > 20 (trending)
    
    Short Entry:
    - 9 EMA < 21 EMA < 50 EMA (bearish alignment)
    - Price pulls back to 9 EMA
    - MACD histogram negative
    - ADX > 20 (trending)
    """
    
    name = "EMATrendFollowingStrategy"
    max_positions = 3  # Max 3 concurrent trades per strategy
    max_positions_per_symbol = 1  # One trade per symbol
    
    def __init__(self, params: dict = None):
        super().__init__(params)
        
        # Per-symbol state
        self.indicators = {}
        self.last_signal_time = {}
        self.prev_ema_alignment = {}  # Track EMA alignment changes
        
        # Parameters
        self.fast_ema = self.params.get("fast_ema", 9)
        self.mid_ema = self.params.get("mid_ema", 21)
        self.slow_ema = self.params.get("slow_ema", 50)
        self.pullback_threshold = self.params.get("pullback_threshold", 0.0003)  # 0.03% from EMA
        self.adx_period = self.params.get("adx_period", 14)
        self.adx_threshold = self.params.get("adx_threshold", 20)
        
        # Risk management
        self.stop_loss_pct = self.params.get("stop_loss_pct", 0.008)  # 0.8%
        self.take_profit_pct = self.params.get("take_profit_pct", 0.024)  # 2.4% (3:1 R:R)
        
        # Cooldown - Reduced from 15 to 10 minutes to capture more setups
        self.cooldown_minutes = self.params.get("cooldown_minutes", 10)
    
    def on_tick(self, symbol: str, price: float, timestamp: datetime) -> Optional[TradeSignal]:
        # Initialize per-symbol state
        if symbol not in self.indicators:
            self.indicators[symbol] = Indicators(max_history=200)
            self.prev_ema_alignment[symbol] = None
        
        # Check cooldown
        if symbol in self.last_signal_time:
            time_since_signal = (timestamp - self.last_signal_time[symbol]).total_seconds() / 60
            if time_since_signal < self.cooldown_minutes:
                return None
        
        # Add price to indicator calculator
        self.indicators[symbol].add(price)
        
        # Need enough data
        if self.indicators[symbol].count < max(self.slow_ema + 20, 100):
            return None
        
        # Calculate EMAs
        ema_fast = self.indicators[symbol].ema(self.fast_ema)
        ema_mid = self.indicators[symbol].ema(self.mid_ema)
        ema_slow = self.indicators[symbol].ema(self.slow_ema)
        
        # Calculate other indicators
        macd_line, signal_line, macd_hist = self.indicators[symbol].macd()
        adx = self.indicators[symbol].adx(self.adx_period)
        
        if None in (ema_fast, ema_mid, ema_slow, macd_hist, adx):
            return None
        
        # Only trade in trending markets
        if adx < self.adx_threshold:
            return None
        
        # Determine EMA alignment
        bullish_alignment = ema_fast > ema_mid > ema_slow
        bearish_alignment = ema_fast < ema_mid < ema_slow
        
        # Check if price is near the fast EMA (pullback)
        distance_from_fast_ema = abs(price - ema_fast) / price
        near_fast_ema = distance_from_fast_ema < self.pullback_threshold
        
        # Long signal: Bullish alignment + pullback to fast EMA + positive MACD
        if bullish_alignment and near_fast_ema and macd_hist > 0 and price > ema_fast:
            self.last_signal_time[symbol] = timestamp
            
            # Use mid EMA as dynamic stop
            stop_loss = max(price * (1 - self.stop_loss_pct), ema_mid * 0.998)
            take_profit = price * (1 + self.take_profit_pct)
            
            # Confidence based on trend strength
            ema_spread = (ema_fast - ema_slow) / ema_slow  # Wider spread = stronger trend
            trend_strength = min(abs(ema_spread) * 100, 1.0)
            macd_strength = min(abs(macd_hist) * 1000, 1.0)
            adx_strength = min((adx - self.adx_threshold) / 30, 1.0)
            
            confidence = 0.65 + (trend_strength * 0.15) + (macd_strength * 0.1) + (adx_strength * 0.1)
            
            return self.create_signal(
                symbol=symbol,
                direction="LONG",
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=min(0.95, confidence),
                reason=f"Bullish EMA alignment, pullback to {ema_fast:.5f}, MACD={macd_hist:.5f}, ADX={adx:.1f}"
            )
        
        # Short signal: Bearish alignment + pullback to fast EMA + negative MACD
        if bearish_alignment and near_fast_ema and macd_hist < 0 and price < ema_fast:
            self.last_signal_time[symbol] = timestamp
            
            # Use mid EMA as dynamic stop
            stop_loss = min(price * (1 + self.stop_loss_pct), ema_mid * 1.002)
            take_profit = price * (1 - self.take_profit_pct)
            
            # Confidence based on trend strength
            ema_spread = (ema_slow - ema_fast) / ema_slow  # Wider spread = stronger trend
            trend_strength = min(abs(ema_spread) * 100, 1.0)
            macd_strength = min(abs(macd_hist) * 1000, 1.0)
            adx_strength = min((adx - self.adx_threshold) / 30, 1.0)
            
            confidence = 0.65 + (trend_strength * 0.15) + (macd_strength * 0.1) + (adx_strength * 0.1)
            
            return self.create_signal(
                symbol=symbol,
                direction="SHORT",
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=min(0.95, confidence),
                reason=f"Bearish EMA alignment, pullback to {ema_fast:.5f}, MACD={macd_hist:.5f}, ADX={adx:.1f}"
            )
        
        return None
