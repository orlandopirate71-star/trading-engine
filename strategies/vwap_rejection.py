"""
VWAP Rejection Strategy - Mean reversion using VWAP.

From Brain:
- Use VWAP rejection trades to profit from price movements rejecting the VWAP line
- Best on 5-minute or 15-minute charts
- Best during trending markets with a sloping VWAP line
- Look for rejection candles at VWAP
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy_loader import BaseStrategy
from indicators import Indicators
from datetime import datetime
from typing import Optional, List
from models import TradeSignal


class VWAPRejectionStrategy(BaseStrategy):
    """
    VWAP Rejection - trades rejections at the Volume Weighted Average Price.
    
    Long Setup:
    - Price in uptrend (VWAP sloping up)
    - Price pulls back to VWAP
    - Rejection candle forms (bullish)
    
    Short Setup:
    - Price in downtrend (VWAP sloping down)
    - Price rallies to VWAP
    - Rejection candle forms (bearish)
    """
    
    name = "VWAPRejectionStrategy"
    
    def __init__(self, params: dict = None):
        super().__init__(params)
        
        self.ind = Indicators(max_history=500)
        
        # VWAP touch tolerance
        self.touch_tolerance = self.params.get("touch_tolerance", 0.002)  # 0.2%
        
        # Trend detection (VWAP slope)
        self.slope_period = self.params.get("slope_period", 50)
        self.min_slope = self.params.get("min_slope", 0.0001)  # Minimum slope for trend
        
        # Risk/reward
        self.risk_reward = self.params.get("risk_reward", 2.0)
        
        # Cooldown
        self.cooldown_ticks = self.params.get("cooldown_ticks", 100)
        self.ticks_since_signal = self.cooldown_ticks
        
        # Track VWAP history for slope
        self.vwap_history: List[float] = []
        
        # Track recent prices for rejection detection
        self.recent_prices: List[float] = []
        
        # Volume simulation (since we may not have real volume)
        self.volume_estimate = 1.0
        
        # Touch tracking
        self.touched_vwap = False
        self.touch_side = None  # "above" or "below"
    
    def _calculate_vwap_slope(self) -> Optional[float]:
        """Calculate VWAP slope to determine trend."""
        if len(self.vwap_history) < self.slope_period:
            return None
        
        recent = self.vwap_history[-self.slope_period:]
        old_vwap = recent[0]
        new_vwap = recent[-1]
        
        if old_vwap == 0:
            return None
        
        return (new_vwap - old_vwap) / old_vwap
    
    def _is_near_vwap(self, price: float, vwap: float) -> bool:
        """Check if price is near VWAP."""
        if vwap == 0:
            return False
        distance = abs(price - vwap) / vwap
        return distance < self.touch_tolerance
    
    def _is_bullish_rejection(self) -> bool:
        """Check for bullish rejection at VWAP."""
        if len(self.recent_prices) < 5:
            return False
        
        recent = self.recent_prices[-5:]
        low = min(recent)
        current = recent[-1]
        
        # Price dipped and recovered
        return current > low * 1.001 and recent.index(low) in [1, 2, 3]
    
    def _is_bearish_rejection(self) -> bool:
        """Check for bearish rejection at VWAP."""
        if len(self.recent_prices) < 5:
            return False
        
        recent = self.recent_prices[-5:]
        high = max(recent)
        current = recent[-1]
        
        # Price spiked and fell
        return current < high * 0.999 and recent.index(high) in [1, 2, 3]
    
    def on_tick(self, symbol: str, price: float, timestamp: datetime) -> Optional[TradeSignal]:
        # Add price with estimated volume
        self.ind.add(price, volume=self.volume_estimate)
        self.ticks_since_signal += 1
        
        # Track recent prices
        self.recent_prices.append(price)
        if len(self.recent_prices) > 20:
            self.recent_prices.pop(0)
        
        # Need enough data
        if self.ind.count < 100:
            return None
        
        # Calculate VWAP (simplified - using SMA as proxy if no volume)
        vwap = self.ind.sma(50)  # Use SMA as VWAP proxy
        
        if vwap is None:
            return None
        
        # Track VWAP history
        self.vwap_history.append(vwap)
        if len(self.vwap_history) > self.slope_period + 10:
            self.vwap_history.pop(0)
        
        # Cooldown
        if self.ticks_since_signal < self.cooldown_ticks:
            return None
        
        # Calculate VWAP slope (trend direction)
        slope = self._calculate_vwap_slope()
        if slope is None:
            return None
        
        uptrend = slope > self.min_slope
        downtrend = slope < -self.min_slope
        
        # Check for VWAP touch
        near_vwap = self._is_near_vwap(price, vwap)
        
        if near_vwap:
            self.touched_vwap = True
            self.touch_side = "above" if price > vwap else "below"
        
        # Long: uptrend + touched VWAP from above + bullish rejection
        if uptrend and self.touched_vwap and self.touch_side == "above" and self._is_bullish_rejection():
            self.ticks_since_signal = 0
            self.touched_vwap = False
            
            atr = self.ind.atr(14) or (price * 0.01)
            stop_loss = price - (atr * 1.5)
            take_profit = price + (atr * 1.5 * self.risk_reward)
            
            return self.create_signal(
                symbol=symbol,
                direction="LONG",
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=0.7,
                reason=f"Bullish VWAP rejection, slope={slope*100:.3f}%"
            )
        
        # Short: downtrend + touched VWAP from below + bearish rejection
        if downtrend and self.touched_vwap and self.touch_side == "below" and self._is_bearish_rejection():
            self.ticks_since_signal = 0
            self.touched_vwap = False
            
            atr = self.ind.atr(14) or (price * 0.01)
            stop_loss = price + (atr * 1.5)
            take_profit = price - (atr * 1.5 * self.risk_reward)
            
            return self.create_signal(
                symbol=symbol,
                direction="SHORT",
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=0.7,
                reason=f"Bearish VWAP rejection, slope={slope*100:.3f}%"
            )
        
        # Reset touch if price moved away
        if not near_vwap and abs(price - vwap) / vwap > self.touch_tolerance * 3:
            self.touched_vwap = False
        
        return None
