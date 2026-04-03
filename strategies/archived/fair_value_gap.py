"""
Fair Value Gap Fill Strategy - Price imbalance fill.

From Brain:
- Identify fair value gaps (FVG) left by impulsive moves
- Gap = area between candle 1 high and candle 3 low (bullish) or vice versa
- Trade the fill of these gaps
- Best in trending markets
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy_loader import BaseStrategy
from indicators import Indicators
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass
from models import TradeSignal


@dataclass
class FVG:
    """Fair Value Gap."""
    direction: str  # "bullish" or "bearish"
    top: float
    bottom: float
    timestamp: datetime
    filled: bool = False


class FairValueGapStrategy(BaseStrategy):
    """
    Fair Value Gap Fill - trades the fill of price imbalances.
    
    Bullish FVG:
    - Candle 1 high < Candle 3 low (gap up)
    - Wait for price to return and fill the gap
    - Go long at the gap
    
    Bearish FVG:
    - Candle 1 low > Candle 3 high (gap down)
    - Wait for price to return and fill the gap
    - Go short at the gap
    """
    
    name = "FairValueGapStrategy"
    symbols = None  # Uses all active symbols from feed_config.json
    
    def __init__(self, params: dict = None):
        super().__init__(params)
        
        # Per-symbol state
        self.indicators = {}  # symbol -> Indicators
        
        # FVG settings
        self.min_gap_size = self.params.get("min_gap_size", 0.001)  # Minimum gap size (0.1%)
        self.max_gap_age = self.params.get("max_gap_age", 500)  # Max ticks before gap expires
        
        # Risk/reward
        self.risk_reward = self.params.get("risk_reward", 2.0)
        
        # Cooldown
        self.cooldown_ticks = self.params.get("cooldown_ticks", 50)
        self.ticks_since_signal = {}  # symbol -> ticks
        
        # Track candles per symbol (simulated from ticks)
        self.candle_highs = {}  # symbol -> List[float]
        self.candle_lows = {}  # symbol -> List[float]
        self.candle_closes = {}  # symbol -> List[float]
        self.ticks_per_candle = self.params.get("ticks_per_candle", 20)
        self.current_candle_ticks = {}  # symbol -> int
        self.current_high = {}  # symbol -> float
        self.current_low = {}  # symbol -> float
        
        # Active FVGs per symbol
        self.fvgs = {}  # symbol -> List[FVG]
        self.tick_count = {}  # symbol -> int
    
    def _init_symbol(self, symbol: str):
        """Initialize per-symbol state."""
        if symbol not in self.indicators:
            self.indicators[symbol] = Indicators(max_history=200)
            self.ticks_since_signal[symbol] = self.cooldown_ticks
            self.candle_highs[symbol] = []
            self.candle_lows[symbol] = []
            self.candle_closes[symbol] = []
            self.current_candle_ticks[symbol] = 0
            self.current_high[symbol] = None
            self.current_low[symbol] = None
            self.fvgs[symbol] = []
            self.tick_count[symbol] = 0
    
    def _complete_candle(self, symbol: str, price: float):
        """Complete current candle and start new one."""
        if self.current_high[symbol] is not None:
            self.candle_highs[symbol].append(self.current_high[symbol])
            self.candle_lows[symbol].append(self.current_low[symbol])
            self.candle_closes[symbol].append(price)
            
            # Keep limited history
            if len(self.candle_highs[symbol]) > 100:
                self.candle_highs[symbol].pop(0)
                self.candle_lows[symbol].pop(0)
                self.candle_closes[symbol].pop(0)
        
        self.current_high[symbol] = price
        self.current_low[symbol] = price
        self.current_candle_ticks[symbol] = 0
    
    def _detect_fvg(self, symbol: str, timestamp: datetime):
        """Detect new fair value gaps."""
        if len(self.candle_highs[symbol]) < 3:
            return
        
        # Get last 3 candles
        h1, h2, h3 = self.candle_highs[symbol][-3:]
        l1, l2, l3 = self.candle_lows[symbol][-3:]
        
        # Bullish FVG: Candle 1 high < Candle 3 low (gap up)
        if h1 < l3:
            gap_size = (l3 - h1) / h1
            if gap_size >= self.min_gap_size:
                fvg = FVG(
                    direction="bullish",
                    top=l3,
                    bottom=h1,
                    timestamp=timestamp
                )
                self.fvgs[symbol].append(fvg)
        
        # Bearish FVG: Candle 1 low > Candle 3 high (gap down)
        if l1 > h3:
            gap_size = (l1 - h3) / l1
            if gap_size >= self.min_gap_size:
                fvg = FVG(
                    direction="bearish",
                    top=l1,
                    bottom=h3,
                    timestamp=timestamp
                )
                self.fvgs[symbol].append(fvg)
    
    def _cleanup_fvgs(self, symbol: str):
        """Remove old or filled FVGs."""
        self.fvgs[symbol] = [
            fvg for fvg in self.fvgs[symbol] 
            if not fvg.filled and (self.tick_count[symbol] - self.max_gap_age) < self.tick_count[symbol]
        ]
        # Keep only recent FVGs
        self.fvgs[symbol] = self.fvgs[symbol][-20:]
    
    def on_tick(self, symbol: str, price: float, timestamp: datetime) -> Optional[TradeSignal]:
        # Initialize per-symbol state
        self._init_symbol(symbol)
        
        self.indicators[symbol].add(price)
        self.tick_count[symbol] += 1
        self.ticks_since_signal[symbol] += 1
        
        # Update current candle
        if self.current_high[symbol] is None:
            self.current_high[symbol] = price
            self.current_low[symbol] = price
        else:
            self.current_high[symbol] = max(self.current_high[symbol], price)
            self.current_low[symbol] = min(self.current_low[symbol], price)
        
        self.current_candle_ticks[symbol] += 1
        
        # Complete candle
        if self.current_candle_ticks[symbol] >= self.ticks_per_candle:
            self._complete_candle(symbol, price)
            self._detect_fvg(symbol, timestamp)
        
        # Need some candles
        if len(self.candle_highs[symbol]) < 5:
            return None
        
        # Cooldown
        if self.ticks_since_signal[symbol] < self.cooldown_ticks:
            return None
        
        # Check if price enters any FVG
        for fvg in self.fvgs[symbol]:
            if fvg.filled:
                continue
            
            # Price entering bullish FVG (go long)
            if fvg.direction == "bullish" and fvg.bottom <= price <= fvg.top:
                fvg.filled = True
                self.ticks_since_signal[symbol] = 0
                
                gap_size = fvg.top - fvg.bottom
                stop_loss = fvg.bottom - gap_size
                take_profit = price + (gap_size * self.risk_reward)
                
                return self.create_signal(
                    symbol=symbol,
                    direction="LONG",
                    entry_price=price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    confidence=0.65,
                    reason=f"Bullish FVG fill at {fvg.bottom:.5f}-{fvg.top:.5f}"
                )
            
            # Price entering bearish FVG (go short)
            if fvg.direction == "bearish" and fvg.bottom <= price <= fvg.top:
                fvg.filled = True
                self.ticks_since_signal[symbol] = 0
                
                gap_size = fvg.top - fvg.bottom
                stop_loss = fvg.top + gap_size
                take_profit = price - (gap_size * self.risk_reward)
                
                return self.create_signal(
                    symbol=symbol,
                    direction="SHORT",
                    entry_price=price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    confidence=0.65,
                    reason=f"Bearish FVG fill at {fvg.bottom:.5f}-{fvg.top:.5f}"
                )
        
        self._cleanup_fvgs(symbol)
        return None


# Alias for strategy loader
FairValueGap = FairValueGapStrategy
