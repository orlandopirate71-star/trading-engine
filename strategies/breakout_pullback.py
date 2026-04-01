"""
Breakout Pullback Continuation Strategy - Trade pullbacks after breakouts.

From Brain:
- Wait for a breakout of key level (support/resistance)
- Wait for pullback to the broken level
- Enter on confirmation of continuation
- Best for trend continuation trades
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
class Level:
    """Support/Resistance level."""
    price: float
    type: str  # "support" or "resistance"
    touches: int = 1
    broken: bool = False
    break_direction: str = None  # "up" or "down"


class BreakoutPullbackStrategy(BaseStrategy):
    """
    Breakout Pullback Continuation - trades pullbacks to broken levels.
    
    Setup:
    1. Identify key support/resistance levels
    2. Wait for breakout through level
    3. Wait for pullback to the broken level (now flipped)
    4. Enter on rejection/continuation
    
    Support becomes resistance after broken down.
    Resistance becomes support after broken up.
    """
    
    name = "BreakoutPullbackStrategy"
    symbols = None  # Uses all active symbols from feed_config.json
    
    def __init__(self, params: dict = None):
        super().__init__(params)
        
        self.indicators = {}  # Dict of symbol -> Indicators
        
        # Level detection
        self.lookback = self.params.get("lookback", 100)
        self.touch_tolerance = self.params.get("touch_tolerance", 0.001)  # 0.1%
        self.min_touches = self.params.get("min_touches", 2)
        
        # Breakout confirmation
        self.breakout_buffer = self.params.get("breakout_buffer", 0.002)  # 0.2%
        
        # Pullback tolerance
        self.pullback_tolerance = self.params.get("pullback_tolerance", 0.003)  # 0.3%
        
        # Risk/reward
        self.risk_reward = self.params.get("risk_reward", 2.0)

        # Trailing stop settings (in profit $ amount)
        self.trailing_stop_trigger = self.params.get("trailing_stop_trigger", 0)  # 0 = disabled
        self.trailing_stop_lock = self.params.get("trailing_stop_lock", 0)

        # Cooldown
        self.cooldown_ticks = self.params.get("cooldown_ticks", 100)
        self.ticks_since_signal = {}  # Dict of symbol -> ticks
        
        # Track levels per symbol
        self.levels = {}  # Dict of symbol -> List[Level]
        self.price_history = {}  # Dict of symbol -> List[float]
        
        # State tracking per symbol
        self.last_level_update = {}  # Dict of symbol -> int
        self.level_update_interval = 50
    
    def _get_symbol_state(self, symbol: str):
        """Initialize per-symbol state if needed."""
        if symbol not in self.indicators:
            self.indicators[symbol] = Indicators(max_history=300)
            self.ticks_since_signal[symbol] = self.cooldown_ticks
            self.levels[symbol] = []
            self.price_history[symbol] = []
            self.last_level_update[symbol] = 0
    
    def _find_swing_points(self, symbol: str) -> tuple:
        """Find swing highs and lows."""
        if len(self.price_history[symbol]) < self.lookback:
            return [], []
        
        prices = self.price_history[symbol][-self.lookback:]
        swing_highs = []
        swing_lows = []
        
        for i in range(5, len(prices) - 5):
            # Swing high
            if prices[i] == max(prices[i-5:i+6]):
                swing_highs.append(prices[i])
            # Swing low
            if prices[i] == min(prices[i-5:i+6]):
                swing_lows.append(prices[i])
        
        return swing_highs, swing_lows
    
    def _update_levels(self, symbol: str, price: float):
        """Update support/resistance levels."""
        swing_highs, swing_lows = self._find_swing_points(symbol)
        
        # Group similar price levels
        def cluster_levels(prices: List[float], tolerance: float) -> List[tuple]:
            if not prices:
                return []
            
            clusters = []
            prices = sorted(prices)
            current_cluster = [prices[0]]
            
            for p in prices[1:]:
                if abs(p - current_cluster[-1]) / current_cluster[-1] < tolerance:
                    current_cluster.append(p)
                else:
                    clusters.append((sum(current_cluster) / len(current_cluster), len(current_cluster)))
                    current_cluster = [p]
            
            clusters.append((sum(current_cluster) / len(current_cluster), len(current_cluster)))
            return clusters
        
        # Find resistance levels (from swing highs)
        resistance_clusters = cluster_levels(swing_highs, self.touch_tolerance)
        for level_price, touches in resistance_clusters:
            if touches >= self.min_touches:
                # Check if level already exists
                existing = next((l for l in self.levels[symbol] if abs(l.price - level_price) / level_price < self.touch_tolerance), None)
                if existing:
                    existing.touches = max(existing.touches, touches)
                else:
                    self.levels[symbol].append(Level(price=level_price, type="resistance", touches=touches))
        
        # Find support levels (from swing lows)
        support_clusters = cluster_levels(swing_lows, self.touch_tolerance)
        for level_price, touches in support_clusters:
            if touches >= self.min_touches:
                existing = next((l for l in self.levels[symbol] if abs(l.price - level_price) / level_price < self.touch_tolerance), None)
                if existing:
                    existing.touches = max(existing.touches, touches)
                else:
                    self.levels[symbol].append(Level(price=level_price, type="support", touches=touches))
        
        # Keep only relevant levels (near current price)
        self.levels[symbol] = [l for l in self.levels[symbol] if abs(l.price - price) / price < 0.05][-20:]
    
    def _check_breakouts(self, symbol: str, price: float, prev_price: float):
        """Check for breakouts of levels."""
        for level in self.levels[symbol]:
            if level.broken:
                continue
            
            # Breakout above resistance
            if level.type == "resistance":
                breakout_price = level.price * (1 + self.breakout_buffer)
                if prev_price < breakout_price and price > breakout_price:
                    level.broken = True
                    level.break_direction = "up"
                    level.type = "support"  # Flip to support
            
            # Breakout below support
            if level.type == "support":
                breakout_price = level.price * (1 - self.breakout_buffer)
                if prev_price > breakout_price and price < breakout_price:
                    level.broken = True
                    level.break_direction = "down"
                    level.type = "resistance"  # Flip to resistance
    
    def _check_pullback(self, symbol: str, price: float) -> Optional[Level]:
        """Check if price is pulling back to a broken level."""
        for level in self.levels[symbol]:
            if not level.broken:
                continue
            
            # Check if price is near the broken level
            distance = abs(price - level.price) / level.price
            if distance < self.pullback_tolerance:
                return level
        
        return None
    
    def _get_atr_multiplier(self, symbol: str, price: float) -> float:
        """Get ATR multiplier based on instrument type and price scale."""
        # Metals need larger ATR multipliers due to different price scale
        if symbol.startswith(("XAU", "XAG", "XPT", "XPD")):
            return 5.0  # 5x multiplier for metals
        # JPY pairs have different scale
        if "JPY" in symbol:
            return 2.0
        # Crypto
        if symbol.startswith(("BTC", "ETH")):
            return 3.0
        # Standard forex
        return 1.0

    def on_tick(self, symbol: str, price: float, timestamp: datetime) -> Optional[TradeSignal]:
        # Initialize per-symbol state
        self._get_symbol_state(symbol)
        
        self.indicators[symbol].add(price)
        self.ticks_since_signal[symbol] += 1
        
        # Track price history
        prev_price = self.price_history[symbol][-1] if self.price_history[symbol] else price
        self.price_history[symbol].append(price)
        if len(self.price_history[symbol]) > self.lookback + 50:
            self.price_history[symbol].pop(0)
        
        # Update levels periodically
        self.last_level_update[symbol] += 1
        if self.last_level_update[symbol] >= self.level_update_interval:
            self._update_levels(symbol, price)
            self.last_level_update[symbol] = 0
        
        # Check for breakouts
        self._check_breakouts(symbol, price, prev_price)
        
        # Need enough data
        if len(self.price_history[symbol]) < self.lookback:
            return None
        
        # Cooldown
        if self.ticks_since_signal[symbol] < self.cooldown_ticks:
            return None
        
        # Check for pullback to broken level
        pullback_level = self._check_pullback(symbol, price)
        if pullback_level is None:
            return None
        
        atr = self.indicators[symbol].atr(14) or (price * 0.01)
        
        # Long: broken resistance (now support), price pulling back
        if pullback_level.break_direction == "up" and price >= pullback_level.price:
            self.ticks_since_signal[symbol] = 0
            pullback_level.broken = False  # Reset so we don't trade again
            
            # Scale ATR appropriately for instrument type
            atr_multiplier = self._get_atr_multiplier(symbol, price)
            scaled_atr = atr * atr_multiplier
            
            stop_loss = pullback_level.price - scaled_atr
            take_profit = price + (scaled_atr * self.risk_reward)
            
            return self.create_signal(
                symbol=symbol,
                direction="LONG",
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                trailing_stop_trigger=self.trailing_stop_trigger if self.trailing_stop_trigger > 0 else None,
                trailing_stop_lock=self.trailing_stop_lock if self.trailing_stop_lock > 0 else None,
                confidence=0.65 + (pullback_level.touches * 0.05),
                reason=f"Pullback to broken resistance at {pullback_level.price:.5f}"
            )

        # Short: broken support (now resistance), price pulling back
        if pullback_level.break_direction == "down" and price <= pullback_level.price:
            self.ticks_since_signal[symbol] = 0
            pullback_level.broken = False

            # Scale ATR appropriately for instrument type
            atr_multiplier = self._get_atr_multiplier(symbol, price)
            scaled_atr = atr * atr_multiplier

            stop_loss = pullback_level.price + scaled_atr
            take_profit = price - (scaled_atr * self.risk_reward)

            return self.create_signal(
                symbol=symbol,
                direction="SHORT",
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                trailing_stop_trigger=self.trailing_stop_trigger if self.trailing_stop_trigger > 0 else None,
                trailing_stop_lock=self.trailing_stop_lock if self.trailing_stop_lock > 0 else None,
                confidence=0.65 + (pullback_level.touches * 0.05),
                reason=f"Pullback to broken support at {pullback_level.price:.5f}"
            )
        
        return None
