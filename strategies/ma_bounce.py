"""
MA Bounce Strategy - Trend continuation at moving average.

From Brain:
- Price touches or slightly penetrates the 50-period EMA
- Look for rejection candle at the 50 EMA
- Daily trend must be established
- Enter at close of rejection candle
- Stop beyond recent swing high/low
- Target next major support/resistance or 1.5R minimum
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy_loader import BaseStrategy
from indicators import Indicators
from datetime import datetime
from typing import Optional, List
from models import TradeSignal


class MABounceStrategy(BaseStrategy):
    """
    MA Bounce - trades bounces off the 50 EMA in trending markets.
    
    Long Setup:
    - Price in uptrend (above 200 EMA)
    - Price pulls back to 50 EMA
    - Bullish rejection candle forms
    
    Short Setup:
    - Price in downtrend (below 200 EMA)
    - Price rallies to 50 EMA
    - Bearish rejection candle forms
    """
    
    name = "MABounceStrategy"
    
    def __init__(self, params: dict = None):
        super().__init__(params)
        
        # Per-symbol state
        self.indicators = {}
        self.last_signal_time = {}
        self.recent_prices = {}  # Per-symbol recent prices
        
        # EMA periods
        self.fast_ema = self.params.get("fast_ema", 50)
        self.trend_ema = self.params.get("trend_ema", 200)
        
        # Touch tolerance (how close to EMA counts as "touch")
        self.touch_tolerance = self.params.get("touch_tolerance", 0.002)  # 0.2%
        
        # Risk/reward
        self.risk_reward = self.params.get("risk_reward", 1.5)
        
        # Cooldown
        self.cooldown_minutes = self.params.get("cooldown_minutes", 3)
        self.touched_ema = False
        self.touch_price = None
    
    def _is_near_ema(self, price: float, ema: float) -> bool:
        """Check if price is near the EMA."""
        if ema == 0:
            return False
        distance = abs(price - ema) / ema
        return distance < self.touch_tolerance
    
    def _is_bullish_rejection(self, symbol: str) -> bool:
        """Check for bullish rejection (price bounced up from EMA)."""
        if len(self.recent_prices[symbol]) < 5:
            return False
        
        # Price should have dipped and recovered
        recent = self.recent_prices[symbol][-5:]
        low_idx = recent.index(min(recent))
        current = recent[-1]
        low = min(recent)
        
        # Low should be in the middle, current should be higher
        return low_idx in [1, 2, 3] and current > low * 1.001
    
    def _is_bearish_rejection(self, symbol: str) -> bool:
        """Check for bearish rejection (price bounced down from EMA)."""
        if len(self.recent_prices[symbol]) < 5:
            return False
        
        # Price should have spiked and fallen
        recent = self.recent_prices[symbol][-5:]
        high_idx = recent.index(max(recent))
        current = recent[-1]
        high = max(recent)
        
        # High should be in the middle, current should be lower
        return high_idx in [1, 2, 3] and current < high * 0.999
    
    def on_tick(self, symbol: str, price: float, timestamp: datetime) -> Optional[TradeSignal]:
        # Initialize per-symbol state
        if symbol not in self.indicators:
            self.indicators[symbol] = Indicators(max_history=250)
            self.recent_prices[symbol] = []
        
        # Check cooldown
        if symbol in self.last_signal_time:
            time_since_signal = (timestamp - self.last_signal_time[symbol]).total_seconds() / 60
            if time_since_signal < self.cooldown_minutes:
                return None
        
        # Add price
        self.indicators[symbol].add(price)
        
        # Track recent prices
        self.recent_prices[symbol].append(price)
        if len(self.recent_prices[symbol]) > 20:
            self.recent_prices[symbol].pop(0)
        
        # Need enough data for EMAs
        if self.indicators[symbol].count < self.trend_ema + 10:
            return None
        
        # Calculate EMAs
        ema_50 = self.indicators[symbol].ema(self.fast_ema)
        ema_200 = self.indicators[symbol].ema(self.trend_ema)
        
        if ema_50 is None or ema_200 is None:
            return None
        
        # Determine trend
        uptrend = price > ema_200 and ema_50 > ema_200
        downtrend = price < ema_200 and ema_50 < ema_200
        
        # Check if price touched EMA
        if self._is_near_ema(price, ema_50):
            self.touched_ema = True
            self.touch_price = price
        
        # Long setup: uptrend + touched EMA + bullish rejection
        if uptrend and self.touched_ema and self._is_bullish_rejection(symbol):
            self.last_signal_time[symbol] = timestamp
            self.touched_ema = False
            
            # Stop below recent low
            recent_low = min(self.recent_prices[symbol][-10:])
            stop_loss = recent_low * 0.998
            risk = price - stop_loss
            take_profit = price + (risk * self.risk_reward)
            
            return self.create_signal(
                symbol=symbol,
                direction="LONG",
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=0.7,
                reason=f"Bullish bounce off 50 EMA in uptrend"
            )
        
        # Short setup: downtrend + touched EMA + bearish rejection
        if downtrend and self.touched_ema and self._is_bearish_rejection(symbol):
            self.last_signal_time[symbol] = timestamp
            self.touched_ema = False
            
            # Stop above recent high
            recent_high = max(self.recent_prices[symbol][-10:])
            stop_loss = recent_high * 1.002
            risk = stop_loss - price
            take_profit = price - (risk * self.risk_reward)
            
            return self.create_signal(
                symbol=symbol,
                direction="SHORT",
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=0.7,
                reason=f"Bearish bounce off 50 EMA in downtrend"
            )
        
        # Reset touch flag if price moved away
        if not self._is_near_ema(price, ema_50):
            if abs(price - ema_50) / ema_50 > self.touch_tolerance * 3:
                self.touched_ema = False
        
        return None
