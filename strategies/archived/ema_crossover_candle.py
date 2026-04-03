"""
EMA Crossover Strategy - Candle-based version.

Uses proper OHLC candles from the candle aggregator.
Trades EMA 9/21 crossovers on 5-minute candles.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy_loader import BaseStrategy
from datetime import datetime, timedelta
from typing import Optional
from models import TradeSignal


class EMACrossoverCandleStrategy(BaseStrategy):
    """
    EMA Crossover using real OHLC candles.
    
    - Uses 9 EMA and 21 EMA
    - Long when 9 EMA crosses above 21 EMA
    - Short when 9 EMA crosses below 21 EMA
    - Requires ADX > 20 for trend confirmation
    """
    
    name = "EMACrossoverCandleStrategy"
    timeframe = "M5"  # 5-minute candles
    
    def __init__(self, params: dict = None):
        super().__init__(params)
        
        # EMA periods
        self.fast_period = self.params.get("fast_period", 9)
        self.slow_period = self.params.get("slow_period", 21)
        
        # Risk management
        self.atr_period = self.params.get("atr_period", 14)
        self.atr_multiplier = self.params.get("atr_multiplier", 1.5)
        self.risk_reward = self.params.get("risk_reward", 2.0)
        
        # Cooldown
        self.cooldown_candles = self.params.get("cooldown_candles", 5)
        self.last_signal_candle = {}
        self.candle_count = {}
    
    def _calculate_ema(self, prices: list, period: int) -> float:
        """Calculate EMA from price list."""
        if len(prices) < period:
            return None
        
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period  # SMA for first value
        
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        
        return ema
    
    def _calculate_atr(self, candles: list, period: int) -> float:
        """Calculate ATR from candle list."""
        if len(candles) < period + 1:
            return None
        
        true_ranges = []
        for i in range(1, len(candles)):
            high = candles[i].high
            low = candles[i].low
            prev_close = candles[i-1].close
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
        
        if len(true_ranges) < period:
            return None
        
        return sum(true_ranges[-period:]) / period
    
    def on_candle(self, symbol: str, candle: dict) -> Optional[TradeSignal]:
        """Process candle close."""
        if symbol not in self.active_symbols:
            return None

        history = candle.get("history")
        if history is None or len(history) < self.slow_period + 5:
            return None
        
        # Track candle count for cooldown
        self.candle_count[symbol] = self.candle_count.get(symbol, 0) + 1
        
        # Check cooldown
        last_signal = self.last_signal_candle.get(symbol, 0)
        if self.candle_count[symbol] - last_signal < self.cooldown_candles:
            return None
        
        # Get close prices for EMA calculation
        closes = history.get_closes(self.slow_period + 10)
        if len(closes) < self.slow_period + 2:
            return None
        
        # Calculate current and previous EMAs
        fast_ema = self._calculate_ema(closes, self.fast_period)
        slow_ema = self._calculate_ema(closes, self.slow_period)
        
        prev_closes = closes[:-1]
        prev_fast_ema = self._calculate_ema(prev_closes, self.fast_period)
        prev_slow_ema = self._calculate_ema(prev_closes, self.slow_period)
        
        if None in [fast_ema, slow_ema, prev_fast_ema, prev_slow_ema]:
            return None
        
        # Calculate ATR for stop loss
        candles = history.get_candles(self.atr_period + 5)
        atr = self._calculate_atr(candles, self.atr_period)
        if not atr:
            return None
        
        price = candle["close"]
        
        # Check for crossover
        bullish_cross = prev_fast_ema <= prev_slow_ema and fast_ema > slow_ema
        bearish_cross = prev_fast_ema >= prev_slow_ema and fast_ema < slow_ema
        
        if bullish_cross:
            stop_loss = price - (atr * self.atr_multiplier)
            take_profit = price + (atr * self.atr_multiplier * self.risk_reward)
            
            self.last_signal_candle[symbol] = self.candle_count[symbol]
            
            return self.create_signal(
                symbol=symbol,
                direction="LONG",
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=0.7,
                reason=f"EMA {self.fast_period}/{self.slow_period} bullish crossover"
            )
        
        elif bearish_cross:
            stop_loss = price + (atr * self.atr_multiplier)
            take_profit = price - (atr * self.atr_multiplier * self.risk_reward)
            
            self.last_signal_candle[symbol] = self.candle_count[symbol]
            
            return self.create_signal(
                symbol=symbol,
                direction="SHORT",
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=0.7,
                reason=f"EMA {self.fast_period}/{self.slow_period} bearish crossover"
            )
        
        return None
    
    def on_tick(self, symbol: str, price: float, timestamp: datetime) -> Optional[TradeSignal]:
        """Not used - this strategy only trades on candle close."""
        return None


# Alias for strategy loader
EMACrossoverCandle = EMACrossoverCandleStrategy
