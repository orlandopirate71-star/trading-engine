"""
EMA Crossover 1-Minute Scalping Strategy
Based on the "BEST 1 Minute Scalping Strategy EVER" by Riley Coleman

Core Rules:
- 50 EMA and 200 EMA on 1-minute chart
- Golden Cross (50 > 200) for bullish entries
- Death Cross (50 < 200) for bearish entries
- Price above/below both EMAs
- Candlestick confirmation
- 10-15 pip target, 5-7 pip stop loss
- 3-5 minute time limit per trade
"""
from strategy_loader import BaseStrategy
from models import TradeSignal
from typing import Optional, List
from datetime import datetime, timedelta
import pandas as pd


class EMA1MinScalper(BaseStrategy):
    """
    EMA Crossover 1-Minute Scalping Strategy
    
    Based on the popular 1-minute scalping strategy using 50 EMA and 200 EMA.
    
    Entry Rules (Bullish):
    - Price above both 50 EMA and 200 EMA
    - 50 EMA crosses above 200 EMA (Golden Cross)
    - Bullish candle closes above both EMAs
    
    Entry Rules (Bearish):
    - Price below both 50 EMA and 200 EMA  
    - 50 EMA crosses below 200 EMA (Death Cross)
    - Bearish candle closes below both EMAs
    
    Exit Rules:
    - Take Profit: 10-15 pips (default 12)
    - Stop Loss: 5-7 pips (default 6)
    - Time limit: 5 minutes max per trade
    """
    name = "EMA1MinScalper"
    symbols = None
    timeframe = "M1"  # 1-minute chart
    max_positions = 0
    max_positions_per_symbol = 1
    
    def __init__(self, params: dict = None):
        super().__init__(params)
        
        # EMA periods
        self.fast_ema = params.get('fast_ema', 50) if params else 50
        self.slow_ema = params.get('slow_ema', 200) if params else 200
        
        # Risk/Reward (in pips for forex)
        self.tp_pips = params.get('tp_pips', 12) if params else 12  # 12 pips target
        self.sl_pips = params.get('sl_pips', 6) if params else 6    # 6 pips stop
        self.risk_reward = self.tp_pips / self.sl_pips
        
        # Time limit per trade (minutes)
        self.trade_time_limit = params.get('trade_time_limit', 5) if params else 5
        
        # Minimum EMA separation (pip value) - stronger trend requirement
        self.min_ema_separation = params.get('min_ema_separation', 0.0005) if params else 0.0005  # ~5 pips
        
        # Cooldown between signals (bars)
        self.cooldown_bars = params.get('cooldown_bars', 10) if params else 10
        
        # Per-symbol state
        self._last_signal_time = {}  # symbol -> last signal bar index
        self._ema50_history = {}     # symbol -> list of EMA values
        self._ema200_history = {}    # symbol -> list of EMA values
    
    def _calculate_ema(self, prices: List[float], period: int) -> List[float]:
        """Calculate EMA for a list of prices."""
        if len(prices) < period:
            return []
        
        multiplier = 2 / (period + 1)
        ema = [sum(prices[:period]) / period]  # Start with SMA
        
        for price in prices[period:]:
            ema.append((price * multiplier) + (ema[-1] * (1 - multiplier)))
        
        return ema
    
    def _is_bullish_candle(self, open_p: float, close: float) -> bool:
        """Check if candle is bullish."""
        return close > open_p
    
    def _is_bearish_candle(self, open_p: float, close: float) -> bool:
        """Check if candle is bullish."""
        return close < open_p
    
    def _pips_to_price(self, symbol: str, pips: float) -> float:
        """Convert pips to price value based on instrument type."""
        if symbol.startswith(("XAU", "XAG")):
            # Metals - pips are different scale
            return pips * 0.01  # 1 pip = 0.01 for metals
        if "JPY" in symbol:
            # JPY pairs - 2nd decimal is 1 pip
            return pips * 0.01
        # Standard forex - 4th decimal is 1 pip
        return pips * 0.0001
    
    def on_candle(self, symbol: str, candle: dict) -> Optional[TradeSignal]:
        """
        Process 1-minute candle and generate signals.
        """
        history = candle.get('history')
        if not history:
            return None
        
        # Need enough candles for 200 EMA
        candles = history.get_candles(250)
        if len(candles) < self.slow_ema + 10:
            return None
        
        # Initialize symbol state
        if symbol not in self._last_signal_time:
            self._last_signal_time[symbol] = -999
        
        # Get closing prices
        closes = [c.close for c in candles]
        
        # Calculate EMAs
        ema50 = self._calculate_ema(closes, self.fast_ema)
        ema200 = self._calculate_ema(closes, self.slow_ema)
        
        if len(ema50) < 5 or len(ema200) < 5:
            return None
        
        # Align EMAs (EMA50 has more values since it starts earlier)
        ema50 = ema50[-len(ema200):]
        
        # Current and previous values
        curr_50 = ema50[-1]
        curr_200 = ema200[-1]
        prev_50 = ema50[-2]
        prev_200 = ema200[-2]
        
        # Current candle
        curr_candle = candles[-1]
        curr_open = curr_candle.open
        curr_close = curr_candle.close
        curr_high = curr_candle.high
        curr_low = curr_candle.low
        
        # Current bar index (for cooldown)
        current_bar_idx = len(candles) - 1
        
        # Check cooldown
        if current_bar_idx - self._last_signal_time.get(symbol, -999) < self.cooldown_bars:
            return None
        
        # Calculate pip value for this symbol
        pip_value = self._pips_to_price(symbol, 1)
        tp_distance = self._pips_to_price(symbol, self.tp_pips)
        sl_distance = self._pips_to_price(symbol, self.sl_pips)
        
        # Check EMA separation (trend strength)
        ema_separation = abs(curr_50 - curr_200)
        
        # === BULLISH ENTRY ===
        # 1. Golden Cross: 50 EMA crosses above 200 EMA
        # 2. Price above both EMAs
        # 3. Bullish candle close
        # 4. EMAs are separated (strong trend)
        golden_cross = prev_50 <= prev_200 and curr_50 > curr_200
        price_above_emas = curr_close > curr_50 and curr_close > curr_200
        bullish_candle = self._is_bullish_candle(curr_open, curr_close)
        strong_trend = ema_separation >= self.min_ema_separation
        
        if golden_cross and price_above_emas and bullish_candle and strong_trend:
            self._last_signal_time[symbol] = current_bar_idx
            
            entry = curr_close
            stop = entry - sl_distance
            target = entry + tp_distance
            
            return self.create_signal(
                symbol=symbol,
                direction="LONG",
                entry_price=entry,
                stop_loss=stop,
                take_profit=target,
                confidence=0.70,
                reason=f"1M Scalp: Golden Cross | 50/200 EMA | +{self.tp_pips}p/-{self.sl_pips}p"
            )
        
        # === BEARISH ENTRY ===
        # 1. Death Cross: 50 EMA crosses below 200 EMA
        # 2. Price below both EMAs
        # 3. Bearish candle close
        # 4. EMAs are separated (strong trend)
        death_cross = prev_50 >= prev_200 and curr_50 < curr_200
        price_below_emas = curr_close < curr_50 and curr_close < curr_200
        bearish_candle = self._is_bearish_candle(curr_open, curr_close)
        
        if death_cross and price_below_emas and bearish_candle and strong_trend:
            self._last_signal_time[symbol] = current_bar_idx
            
            entry = curr_close
            stop = entry + sl_distance
            target = entry - tp_distance
            
            return self.create_signal(
                symbol=symbol,
                direction="SHORT",
                entry_price=entry,
                stop_loss=stop,
                take_profit=target,
                confidence=0.70,
                reason=f"1M Scalp: Death Cross | 50/200 EMA | +{self.tp_pips}p/-{self.sl_pips}p"
            )
        
        return None
    
    def on_tick(self, symbol: str, price: float, timestamp: datetime) -> Optional[TradeSignal]:
        """Tick-based processing - not used for this candle-based strategy."""
        return None
