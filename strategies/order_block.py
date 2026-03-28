"""
Order Block Reaction Strategy - Institutional level reaction.

From Brain:
- Identify areas where institutional orders accumulated before strong moves
- Order blocks are the last opposing candle before a strong impulsive move
- Trade rejections at these order block levels
- Stop beyond order block extreme
- Target previous swing high/low or 2R minimum
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
class OrderBlock:
    """Order Block level."""
    direction: str  # "bullish" or "bearish"
    high: float
    low: float
    timestamp: datetime
    tested: bool = False
    strength: float = 1.0  # Based on impulsive move size


class OrderBlockStrategy(BaseStrategy):
    """
    Order Block Reaction - trades reactions at institutional order blocks.
    
    Bullish Order Block:
    - Last bearish candle before strong bullish move
    - Go long when price returns to this zone
    
    Bearish Order Block:
    - Last bullish candle before strong bearish move
    - Go short when price returns to this zone
    """
    
    name = "OrderBlockStrategy"
    
    def __init__(self, params: dict = None):
        super().__init__(params)
        
        # Per-symbol state
        self.indicators = {}  # symbol -> Indicators
        
        # Order block detection
        self.min_impulse_size = self.params.get("min_impulse_size", 0.003)  # 0.3% minimum move
        self.ticks_per_candle = self.params.get("ticks_per_candle", 20)
        
        # Risk/reward
        self.risk_reward = self.params.get("risk_reward", 2.0)
        
        # Cooldown
        self.cooldown_ticks = self.params.get("cooldown_ticks", 100)
        self.ticks_since_signal = {}  # symbol -> int
        
        # Candle tracking per symbol
        self.candles = {}  # symbol -> List[dict]
        self.current_candle = {}  # symbol -> dict
        self.candle_tick_count = {}  # symbol -> int
        
        # Active order blocks per symbol
        self.order_blocks = {}  # symbol -> List[OrderBlock]
    
    def _init_symbol(self, symbol: str):
        """Initialize per-symbol state."""
        if symbol not in self.indicators:
            self.indicators[symbol] = Indicators(max_history=200)
            self.ticks_since_signal[symbol] = self.cooldown_ticks
            self.candles[symbol] = []
            self.current_candle[symbol] = None
            self.candle_tick_count[symbol] = 0
            self.order_blocks[symbol] = []
    
    def _start_new_candle(self, symbol: str, price: float):
        """Start a new candle."""
        self.current_candle[symbol] = {
            'open': price,
            'high': price,
            'low': price,
            'close': price
        }
        self.candle_tick_count[symbol] = 0
    
    def _update_candle(self, symbol: str, price: float):
        """Update current candle."""
        if self.current_candle[symbol] is None:
            self._start_new_candle(symbol, price)
            return
        
        self.current_candle[symbol]['high'] = max(self.current_candle[symbol]['high'], price)
        self.current_candle[symbol]['low'] = min(self.current_candle[symbol]['low'], price)
        self.current_candle[symbol]['close'] = price
        self.candle_tick_count[symbol] += 1
    
    def _complete_candle(self, symbol: str):
        """Complete current candle and detect order blocks."""
        if self.current_candle[symbol] is None:
            return
        
        self.candles[symbol].append(self.current_candle[symbol].copy())
        
        # Keep limited history
        if len(self.candles[symbol]) > 50:
            self.candles[symbol].pop(0)
        
        # Detect order blocks (need at least 3 candles)
        if len(self.candles[symbol]) >= 3:
            self._detect_order_blocks(symbol)
        
        self.current_candle[symbol] = None
    
    def _is_bullish_candle(self, candle: dict) -> bool:
        """Check if candle is bullish."""
        return candle['close'] > candle['open']
    
    def _is_bearish_candle(self, candle: dict) -> bool:
        """Check if candle is bearish."""
        return candle['close'] < candle['open']
    
    def _candle_body_size(self, candle: dict) -> float:
        """Get candle body size as percentage."""
        if candle['open'] == 0:
            return 0
        return abs(candle['close'] - candle['open']) / candle['open']
    
    def _detect_order_blocks(self, symbol: str):
        """Detect new order blocks from recent candles."""
        if len(self.candles[symbol]) < 3:
            return
        
        # Check last 3 candles
        c1 = self.candles[symbol][-3]  # Potential order block
        c2 = self.candles[symbol][-2]  # Transition
        c3 = self.candles[symbol][-1]  # Impulsive move
        
        # Bullish Order Block: bearish candle followed by strong bullish move
        if self._is_bearish_candle(c1):
            # Check for strong bullish impulse
            impulse = (c3['close'] - c1['low']) / c1['low'] if c1['low'] > 0 else 0
            
            if impulse >= self.min_impulse_size and self._is_bullish_candle(c3):
                ob = OrderBlock(
                    direction="bullish",
                    high=c1['high'],
                    low=c1['low'],
                    timestamp=datetime.utcnow(),
                    strength=impulse
                )
                self.order_blocks[symbol].append(ob)
        
        # Bearish Order Block: bullish candle followed by strong bearish move
        if self._is_bullish_candle(c1):
            # Check for strong bearish impulse
            impulse = (c1['high'] - c3['close']) / c1['high'] if c1['high'] > 0 else 0
            
            if impulse >= self.min_impulse_size and self._is_bearish_candle(c3):
                ob = OrderBlock(
                    direction="bearish",
                    high=c1['high'],
                    low=c1['low'],
                    timestamp=datetime.utcnow(),
                    strength=impulse
                )
                self.order_blocks[symbol].append(ob)
        
        # Cleanup old order blocks
        self.order_blocks[symbol] = [ob for ob in self.order_blocks[symbol] if not ob.tested][-10:]
    
    def on_tick(self, symbol: str, price: float, timestamp: datetime) -> Optional[TradeSignal]:
        self._init_symbol(symbol)
        self.indicators[symbol].add(price)
        self.ticks_since_signal[symbol] += 1
        
        # Update candle
        self._update_candle(symbol, price)
        
        # Complete candle after enough ticks
        if self.candle_tick_count[symbol] >= self.ticks_per_candle:
            self._complete_candle(symbol)
            self._start_new_candle(symbol, price)
        
        # Need some candles
        if len(self.candles[symbol]) < 5:
            return None
        
        # Cooldown
        if self.ticks_since_signal[symbol] < self.cooldown_ticks:
            return None
        
        # Check if price enters any order block
        for ob in self.order_blocks[symbol]:
            if ob.tested:
                continue
            
            # Price entering bullish order block (go long)
            if ob.direction == "bullish" and ob.low <= price <= ob.high:
                ob.tested = True
                self.ticks_since_signal[symbol] = 0
                
                ob_size = ob.high - ob.low
                stop_loss = ob.low - ob_size  # Beyond OB extreme
                take_profit = price + (ob_size * self.risk_reward * 2)
                
                return self.create_signal(
                    symbol=symbol,
                    direction="LONG",
                    entry_price=price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    confidence=0.65 + (ob.strength * 10),  # Higher confidence for stronger OBs
                    reason=f"Bullish order block reaction at {ob.low:.5f}-{ob.high:.5f}"
                )
            
            # Price entering bearish order block (go short)
            if ob.direction == "bearish" and ob.low <= price <= ob.high:
                ob.tested = True
                self.ticks_since_signal[symbol] = 0
                
                ob_size = ob.high - ob.low
                stop_loss = ob.high + ob_size  # Beyond OB extreme
                take_profit = price - (ob_size * self.risk_reward * 2)
                
                return self.create_signal(
                    symbol=symbol,
                    direction="SHORT",
                    entry_price=price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    confidence=0.65 + (ob.strength * 10),
                    reason=f"Bearish order block reaction at {ob.low:.5f}-{ob.high:.5f}"
                )
        
        return None
