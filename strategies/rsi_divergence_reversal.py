"""
RSI Divergence Reversal Strategy - Momentum reversal using RSI divergence.

From Brain:
- Price makes lower low but RSI makes higher low (bullish divergence)
- OR price makes higher high but RSI makes lower high (bearish divergence)
- Confirmation: Pin bar at support/resistance
- Entry: 50% into pin bar wick
- Target: 1.5R to 2R
- Best on 4H chart, London or NY session
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy_loader import BaseStrategy
from indicators import Indicators
from datetime import datetime
from typing import Optional, List, Tuple
from models import TradeSignal


class RSIDivergenceReversalStrategy(BaseStrategy):
    """
    RSI Divergence Reversal - identifies momentum divergence for reversals.
    
    Bullish Setup:
    - Price makes lower low
    - RSI makes higher low (divergence)
    - Bullish rejection candle at support
    
    Bearish Setup:
    - Price makes higher high
    - RSI makes lower high (divergence)
    - Bearish rejection candle at resistance
    """
    
    name = "RSIDivergenceReversalStrategy"
    
    def __init__(self, params: dict = None):
        super().__init__(params)
        
        # Per-symbol state
        self.indicators = {}
        self.last_signal_time = {}
        self.price_history = {}
        self.rsi_history = {}
        self.recent_highs = {}
        self.recent_lows = {}
        
        # RSI settings
        self.rsi_period = self.params.get("rsi_period", 14)
        
        # Divergence lookback (number of swings to check)
        self.divergence_lookback = self.params.get("divergence_lookback", 20)
        
        # Risk/reward
        self.risk_reward = self.params.get("risk_reward", 2.0)
        
        # Cooldown
        self.cooldown_minutes = self.params.get("cooldown_minutes", 5)
    
    def _find_swing_lows(self, data: List[float], count: int = 2) -> List[Tuple[int, float]]:
        """Find recent swing lows in data."""
        swings = []
        for i in range(2, len(data) - 1):
            if data[i] < data[i-1] and data[i] < data[i-2] and data[i] < data[i+1]:
                swings.append((i, data[i]))
        return swings[-count:] if len(swings) >= count else []
    
    def _find_swing_highs(self, data: List[float], count: int = 2) -> List[Tuple[int, float]]:
        """Find recent swing highs in data."""
        swings = []
        for i in range(2, len(data) - 1):
            if data[i] > data[i-1] and data[i] > data[i-2] and data[i] > data[i+1]:
                swings.append((i, data[i]))
        return swings[-count:] if len(swings) >= count else []
    
    def _is_bullish_divergence(self, symbol: str) -> bool:
        """Check for bullish divergence: price lower low, RSI higher low."""
        if len(self.price_history[symbol]) < self.divergence_lookback:
            return False
        
        price_swings = self._find_swing_lows(self.price_history[symbol][-self.divergence_lookback:])
        rsi_swings = self._find_swing_lows(self.rsi_history[symbol][-self.divergence_lookback:])
        
        if len(price_swings) < 2 or len(rsi_swings) < 2:
            return False
        
        # Price made lower low
        price_lower_low = price_swings[-1][1] < price_swings[-2][1]
        # RSI made higher low
        rsi_higher_low = rsi_swings[-1][1] > rsi_swings[-2][1]
        
        return price_lower_low and rsi_higher_low
    
    def _is_bearish_divergence(self, symbol: str) -> bool:
        """Check for bearish divergence: price higher high, RSI lower high."""
        if len(self.price_history[symbol]) < self.divergence_lookback:
            return False
        
        price_swings = self._find_swing_highs(self.price_history[symbol][-self.divergence_lookback:])
        rsi_swings = self._find_swing_highs(self.rsi_history[symbol][-self.divergence_lookback:])
        
        if len(price_swings) < 2 or len(rsi_swings) < 2:
            return False
        
        # Price made higher high
        price_higher_high = price_swings[-1][1] > price_swings[-2][1]
        # RSI made lower high
        rsi_lower_high = rsi_swings[-1][1] < rsi_swings[-2][1]
        
        return price_higher_high and rsi_lower_high
    
    def _is_bullish_pin_bar(self, symbol: str) -> bool:
        """Check for bullish rejection candle (long lower wick)."""
        if len(self.recent_highs[symbol]) < 3 or len(self.recent_lows[symbol]) < 3:
            return False
        
        high = self.recent_highs[symbol][-1]
        low = self.recent_lows[symbol][-1]
        close = self.price_history[symbol][-1]
        open_price = self.price_history[symbol][-2] if len(self.price_history[symbol]) > 1 else close
        
        body = abs(close - open_price)
        total_range = high - low
        lower_wick = min(close, open_price) - low
        
        if total_range == 0:
            return False
        
        # Lower wick should be > 60% of total range, body < 30%
        return lower_wick / total_range > 0.6 and body / total_range < 0.3
    
    def _is_bearish_pin_bar(self, symbol: str) -> bool:
        """Check for bearish rejection candle (long upper wick)."""
        if len(self.recent_highs[symbol]) < 3 or len(self.recent_lows[symbol]) < 3:
            return False
        
        high = self.recent_highs[symbol][-1]
        low = self.recent_lows[symbol][-1]
        close = self.price_history[symbol][-1]
        open_price = self.price_history[symbol][-2] if len(self.price_history[symbol]) > 1 else close
        
        body = abs(close - open_price)
        total_range = high - low
        upper_wick = high - max(close, open_price)
        
        if total_range == 0:
            return False
        
        # Upper wick should be > 60% of total range, body < 30%
        return upper_wick / total_range > 0.6 and body / total_range < 0.3
    
    def on_tick(self, symbol: str, price: float, timestamp: datetime) -> Optional[TradeSignal]:
        # Initialize per-symbol state
        if symbol not in self.indicators:
            self.indicators[symbol] = Indicators(max_history=200)
            self.price_history[symbol] = []
            self.rsi_history[symbol] = []
            self.recent_highs[symbol] = []
            self.recent_lows[symbol] = []
        
        # Check cooldown
        if symbol in self.last_signal_time:
            time_since_signal = (timestamp - self.last_signal_time[symbol]).total_seconds() / 60
            if time_since_signal < self.cooldown_minutes:
                return None
        
        # Add price
        self.indicators[symbol].add(price)
        
        # Track history
        self.price_history[symbol].append(price)
        if len(self.price_history[symbol]) > 200:
            self.price_history[symbol].pop(0)
        
        # Track highs/lows for pin bar detection
        self.recent_highs[symbol].append(price)
        self.recent_lows[symbol].append(price)
        if len(self.recent_highs[symbol]) > 10:
            self.recent_highs[symbol].pop(0)
            self.recent_lows[symbol].pop(0)
        
        # Update high/low within current "candle" (last 10 ticks)
        if len(self.recent_highs[symbol]) >= 2:
            self.recent_highs[symbol][-1] = max(self.recent_highs[symbol][-1], price)
            self.recent_lows[symbol][-1] = min(self.recent_lows[symbol][-1], price)
        
        # Calculate RSI
        rsi = self.indicators[symbol].rsi(self.rsi_period)
        if rsi is None:
            return None
        
        self.rsi_history[symbol].append(rsi)
        if len(self.rsi_history[symbol]) > 200:
            self.rsi_history[symbol].pop(0)
        
        # Need enough data
        if len(self.price_history[symbol]) < self.divergence_lookback:
            return None
        
        # Check for bullish divergence + pin bar
        if self._is_bullish_divergence(symbol) and rsi < 40:
            self.last_signal_time[symbol] = timestamp
            
            recent_low = min(self.price_history[symbol][-10:])
            stop_loss = recent_low * 0.998  # Just below recent low
            risk = price - stop_loss
            take_profit = price + (risk * self.risk_reward)
            
            return self.create_signal(
                symbol=symbol,
                direction="LONG",
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=0.7,
                reason=f"Bullish RSI divergence, RSI={rsi:.1f}"
            )
        
        # Check for bearish divergence + pin bar
        if self._is_bearish_divergence(symbol) and rsi > 60:
            self.last_signal_time[symbol] = timestamp
            
            recent_high = max(self.price_history[symbol][-10:])
            stop_loss = recent_high * 1.002  # Just above recent high
            risk = stop_loss - price
            take_profit = price - (risk * self.risk_reward)
            
            return self.create_signal(
                symbol=symbol,
                direction="SHORT",
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=0.7,
                reason=f"Bearish RSI divergence, RSI={rsi:.1f}"
            )
        
        return None
