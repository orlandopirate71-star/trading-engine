"""
Support/Resistance Bounce Strategy - Trades bounces off key price levels.
Identifies strong S/R zones and enters when price rejects these levels.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy_loader import BaseStrategy
from indicators import Indicators
from datetime import datetime
from typing import Optional, List, Tuple
from models import TradeSignal
import math


class SupportResistanceBounceStrategy(BaseStrategy):
    """
    Support/Resistance bounce strategy:
    - Identifies key S/R levels from recent swing highs/lows
    - Waits for price to approach and reject these levels
    - Confirms with candlestick patterns (hammer/shooting star)
    - Uses RSI for oversold/overbought confirmation
    
    Long Entry:
    - Price approaches support level
    - RSI < 40 (oversold at support)
    - Price bounces with bullish rejection (lower wick > 60% of candle)
    - Volume spike (if available)
    
    Short Entry:
    - Price approaches resistance level
    - RSI > 60 (overbought at resistance)
    - Price rejects with bearish rejection (upper wick > 60% of candle)
    - Volume spike (if available)
    """
    
    name = "SupportResistanceBounceStrategy"
    max_positions = 2  # Max 2 concurrent trades - limit exposure given this strat's volatility
    max_positions_per_symbol = 1  # One trade per symbol
    
    def __init__(self, params: dict = None):
        super().__init__(params)
        
        # Per-symbol state
        self.indicators = {}
        self.last_signal_time = {}
        self.support_levels = {}  # List of support prices
        self.resistance_levels = {}  # List of resistance prices
        self.last_candle = {}  # Track last candle for pattern detection
        
        # Parameters
        self.lookback_candles = self.params.get("lookback_candles", 50)
        self.level_threshold = self.params.get("level_threshold", 0.0002)  # 0.02% proximity to level
        self.min_touches = self.params.get("min_touches", 2)  # Minimum times level was tested
        self.wick_ratio = self.params.get("wick_ratio", 0.6)  # Wick must be 60% of candle
        self.rsi_period = self.params.get("rsi_period", 14)
        self.rsi_support_threshold = self.params.get("rsi_support_threshold", 40)
        self.rsi_resistance_threshold = self.params.get("rsi_resistance_threshold", 60)
        
        # Risk management - ATR-based for proper position sizing across symbols
        self.atr_period = self.params.get("atr_period", 14)
        self.stop_loss_atr = self.params.get("stop_loss_atr", 1.5)  # 1.5x ATR (was 0.6% fixed)
        self.take_profit_atr = self.params.get("take_profit_atr", 3.0)  # 3x ATR target (2:1 R:R)

        # Fallback fixed % for when ATR is not available
        self.stop_loss_pct_fallback = self.params.get("stop_loss_pct_fallback", 0.003)  # 0.3%
        self.take_profit_pct_fallback = self.params.get("take_profit_pct_fallback", 0.006)  # 0.6%

        # Cooldown
        self.cooldown_minutes = self.params.get("cooldown_minutes", 15)
        self.timeframe = "M1"
    
    def _find_swing_points(self, candles: list) -> Tuple[List[float], List[float]]:
        """Find swing highs and lows from candle data."""
        if len(candles) < 5:
            return [], []
        
        swing_highs = []
        swing_lows = []
        
        for i in range(2, len(candles) - 2):
            # Get candle data
            if isinstance(candles[i], dict):
                high = candles[i]['high']
                low = candles[i]['low']
                prev_high = candles[i-1]['high']
                prev_low = candles[i-1]['low']
                next_high = candles[i+1]['high']
                next_low = candles[i+1]['low']
            else:
                high = candles[i].high
                low = candles[i].low
                prev_high = candles[i-1].high
                prev_low = candles[i-1].low
                next_high = candles[i+1].high
                next_low = candles[i+1].low
            
            # Swing high: higher than neighbors
            if high > prev_high and high > next_high:
                swing_highs.append(high)
            
            # Swing low: lower than neighbors
            if low < prev_low and low < next_low:
                swing_lows.append(low)
        
        return swing_highs, swing_lows
    
    def _cluster_levels(self, levels: List[float], threshold: float) -> List[float]:
        """Cluster nearby levels into single S/R zones."""
        if not levels:
            return []
        
        sorted_levels = sorted(levels)
        clusters = []
        current_cluster = [sorted_levels[0]]
        
        for level in sorted_levels[1:]:
            if abs(level - current_cluster[-1]) / level < threshold:
                current_cluster.append(level)
            else:
                # Save cluster average
                clusters.append(sum(current_cluster) / len(current_cluster))
                current_cluster = [level]
        
        # Add last cluster
        if current_cluster:
            clusters.append(sum(current_cluster) / len(current_cluster))
        
        # Only keep levels tested multiple times
        return [c for c in clusters if len([l for l in levels if abs(l - c) / c < threshold]) >= self.min_touches]
    
    def _detect_rejection_candle(self, candle: dict, direction: str) -> bool:
        """Detect bullish/bearish rejection candle patterns."""
        if isinstance(candle, dict):
            open_price = candle['open']
            close = candle['close']
            high = candle['high']
            low = candle['low']
        else:
            open_price = candle.open
            close = candle.close
            high = candle.high
            low = candle.low
        
        body = abs(close - open_price)
        total_range = high - low
        
        if total_range == 0:
            return False
        
        if direction == "LONG":
            # Bullish rejection: long lower wick, small body
            lower_wick = min(open_price, close) - low
            return lower_wick / total_range > self.wick_ratio
        
        elif direction == "SHORT":
            # Bearish rejection: long upper wick, small body
            upper_wick = high - max(open_price, close)
            return upper_wick / total_range > self.wick_ratio
        
        return False
    
    def on_tick(self, symbol: str, price: float, timestamp: datetime) -> Optional[TradeSignal]:
        # Initialize per-symbol state
        if symbol not in self.indicators:
            self.indicators[symbol] = Indicators(max_history=200)
            self.support_levels[symbol] = []
            self.resistance_levels[symbol] = []
        
        # Check cooldown
        if symbol in self.last_signal_time:
            time_since_signal = (timestamp - self.last_signal_time[symbol]).total_seconds() / 60
            if time_since_signal < self.cooldown_minutes:
                return None
        
        # Add price to indicator calculator
        self.indicators[symbol].add(price)
        
        # Need enough data
        if self.indicators[symbol].count < 100:
            return None
        
        # Get recent candles to identify S/R levels
        try:
            from candle_store import get_candle_store
            candle_store = get_candle_store()
            candles = candle_store.get_recent_candles(symbol, self.timeframe, count=self.lookback_candles)
            
            if not candles or len(candles) < 20:
                return None
            
            # Update S/R levels periodically
            swing_highs, swing_lows = self._find_swing_points(candles)
            self.resistance_levels[symbol] = self._cluster_levels(swing_highs, self.level_threshold)
            self.support_levels[symbol] = self._cluster_levels(swing_lows, self.level_threshold)
            
            # Get last closed candle for pattern detection
            if len(candles) >= 2:
                self.last_candle[symbol] = candles[-2]  # Last closed candle
            
        except Exception as e:
            print(f"[S/R Bounce] Error fetching candles for {symbol}: {e}")
            return None
        
        # Calculate RSI and ATR
        rsi = self.indicators[symbol].rsi(self.rsi_period)
        atr = self.indicators[symbol].atr(self.atr_period)
        if rsi is None:
            return None

        # Use ATR-based stops if available, otherwise fallback to fixed %
        if atr and atr > 0:
            sl_distance = atr * self.stop_loss_atr
            tp_distance = atr * self.take_profit_atr
        else:
            sl_distance = price * self.stop_loss_pct_fallback
            tp_distance = price * self.take_profit_pct_fallback

        # Check if price is near any support level
        for support in self.support_levels[symbol]:
            distance = abs(price - support) / price
            if distance < self.level_threshold and price >= support:
                # Check for bullish rejection candle
                if symbol in self.last_candle and self._detect_rejection_candle(self.last_candle[symbol], "LONG"):
                    # RSI confirmation
                    if rsi < self.rsi_support_threshold:
                        self.last_signal_time[symbol] = timestamp

                        # ATR-based or fallback stop loss
                        stop_loss = price - sl_distance
                        take_profit = price + tp_distance
                        
                        # Confidence based on RSI and proximity to level
                        rsi_strength = (self.rsi_support_threshold - rsi) / self.rsi_support_threshold
                        proximity_strength = 1 - (distance / self.level_threshold)
                        confidence = 0.65 + (rsi_strength * 0.15) + (proximity_strength * 0.2)
                        
                        return self.create_signal(
                            symbol=symbol,
                            direction="LONG",
                            entry_price=price,
                            stop_loss=stop_loss,
                            take_profit=take_profit,
                            confidence=min(0.95, confidence),
                            reason=f"Bounce off support {support:.5f}, RSI={rsi:.1f}, rejection candle detected"
                        )
        
        # Check if price is near any resistance level
        for resistance in self.resistance_levels[symbol]:
            distance = abs(price - resistance) / price
            if distance < self.level_threshold and price <= resistance:
                # Check for bearish rejection candle
                if symbol in self.last_candle and self._detect_rejection_candle(self.last_candle[symbol], "SHORT"):
                    # RSI confirmation
                    if rsi > self.rsi_resistance_threshold:
                        self.last_signal_time[symbol] = timestamp

                        # ATR-based or fallback stop loss
                        stop_loss = price + sl_distance
                        take_profit = price - tp_distance
                        
                        # Confidence based on RSI and proximity to level
                        rsi_strength = (rsi - self.rsi_resistance_threshold) / (100 - self.rsi_resistance_threshold)
                        proximity_strength = 1 - (distance / self.level_threshold)
                        confidence = 0.65 + (rsi_strength * 0.15) + (proximity_strength * 0.2)
                        
                        return self.create_signal(
                            symbol=symbol,
                            direction="SHORT",
                            entry_price=price,
                            stop_loss=stop_loss,
                            take_profit=take_profit,
                            confidence=min(0.95, confidence),
                            reason=f"Rejection at resistance {resistance:.5f}, RSI={rsi:.1f}, rejection candle detected"
                        )
        
        return None
