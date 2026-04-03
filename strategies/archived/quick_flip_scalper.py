"""
Quick Flip Scalper Strategy - Based on the "One Candle" Scalping Strategy

Original Strategy Rules (adapted for forex):
1. BOX: Mark the opening range (high/low of first 15m candle)
2. CONFIRM: Check if it's a liquidity candle (large ATR, aggressive move)
3. ENTER: Look for reversal candlestick (hammer/engulfing) outside the box on 5m timeframe

Key Concepts:
- Liquidity candles = manipulation candles that create stop hunts
- Reversal entries after liquidity sweep
- 90 minute time limit from range establishment
"""
from strategy_loader import BaseStrategy
from models import TradeSignal
from typing import Optional
from datetime import datetime, timedelta


class QuickFlipScalper(BaseStrategy):
    """
    Quick Flip Scalper - One Candle Scalping Strategy
    
    Based on the strategy by Carl from the YouTube video:
    "The ONE CANDLE Scalping Strategy I Will Use For Life"
    
    Strategy Steps:
    1. BOX: Mark high/low of opening 15m candle (the "range")
    2. CONFIRM: Verify it's a liquidity candle (ATR > 1.5x recent average)
    3. ENTER: Wait for reversal candle (hammer/engulfing) outside box on 5m
    
    Parameters:
    - Uses 15m for range establishment, 5m for entry signals
    - 90 minute max time from range establishment
    - Targets based on range size (1.5x - 2.5x range)
    """
    name = "QuickFlipScalper"
    symbols = None  # Works on any symbol
    timeframe = "M5"  # Entry timeframe (lower timeframe)
    range_timeframe = "M15"  # Opening range timeframe
    max_positions = 0
    max_positions_per_symbol = 1
    
    def __init__(self, params: dict = None):
        super().__init__(params)
        
        # Range settings
        self.range_bars = params.get('range_bars', 3) if params else 3  # 3 bars = ~15m on 5m chart
        self.max_wait_minutes = params.get('max_wait_minutes', 90) if params else 90
        self.atr_multiplier = params.get('atr_multiplier', 1.5) if params else 1.5  # For liquidity detection
        
        # Risk/Reward
        self.risk_reward = params.get('risk_reward', 2.0) if params else 2.0
        self.sl_buffer = params.get('sl_buffer', 0.0002) if params else 0.0002  # 2 pips buffer
        
        # Reversal pattern settings
        self.min_wick_ratio = params.get('min_wick_ratio', 0.6) if params else 0.6  # For hammer detection
        self.engulfing_body_ratio = params.get('engulfing_body_ratio', 1.2) if params else 1.2
        
        # Per-symbol state
        self._range_high = {}      # symbol -> high of range
        self._range_low = {}       # symbol -> low of range
        self._range_atr = {}       # symbol -> ATR of range candle
        self._range_time = {}      # symbol -> datetime when range established
        self._is_liquidity_candle = {}  # symbol -> bool
        self._range_confirmed = {} # symbol -> bool
        self._candle_count = {}    # symbol -> count of 5m candles
    
    def _get_atr_multiplier(self, symbol: str) -> float:
        """Get ATR multiplier based on instrument type for proper TP/SL scaling.
        
        Metals and JPY pairs have different price scales than standard forex.
        Returns multiplier to scale ATR appropriately.
        """
        symbol_upper = symbol.upper()
        
        # Metals - very high ATR relative to price
        if 'XAU' in symbol_upper or 'GOLD' in symbol_upper:
            return 0.1  # Gold: scale down by 90%
        elif 'XAG' in symbol_upper or 'SILVER' in symbol_upper:
            return 0.15  # Silver: scale down by 85%
        elif 'XPT' in symbol_upper or 'PLATINUM' in symbol_upper:
            return 0.2
        elif 'XPD' in symbol_upper or 'PALLADIUM' in symbol_upper:
            return 0.2
        # JPY pairs - different decimal place convention
        elif 'JPY' in symbol_upper:
            return 0.01  # JPY pairs: scale down significantly
        # Crypto - typically high volatility
        elif any(c in symbol_upper for c in ['BTC', 'ETH', 'SOL', 'ADA', 'DOT', 'LINK', 'UNI']):
            return 0.5
        # Oil and commodities
        elif symbol_upper in ['WTICO', 'BRENT', 'OIL', 'USOIL', 'UKOIL']:
            return 0.3
        
        # Standard forex pairs - no scaling needed
        return 1.0

    def _calculate_atr(self, candles: list, period: int = 14) -> float:
        """Calculate Average True Range."""
        if len(candles) < period + 1:
            return 0
        
        tr_values = []
        for i in range(1, min(period + 1, len(candles))):
            prev_close = candles[i-1].close
            curr_high = candles[i].high
            curr_low = candles[i].low
            
            tr1 = curr_high - curr_low
            tr2 = abs(curr_high - prev_close)
            tr3 = abs(curr_low - prev_close)
            
            tr_values.append(max(tr1, tr2, tr3))
        
        return sum(tr_values) / len(tr_values) if tr_values else 0
    
    def _is_hammer(self, open_p: float, high: float, low: float, close: float, 
                   direction: str = "bullish") -> bool:
        """Check if candle is a hammer pattern."""
        body = abs(close - open_p)
        total_range = high - low
        
        if total_range == 0:
            return False
        
        body_ratio = body / total_range
        
        if direction == "bullish":
            # Bullish hammer: small body at top, long lower wick
            lower_wick = min(open_p, close) - low
            upper_wick = high - max(open_p, close)
            wick_ratio = lower_wick / total_range if total_range > 0 else 0
            
            # Close must be near high (bullish), long lower wick
            return (close > open_p and  # Bullish
                    body_ratio < 0.3 and  # Small body
                    wick_ratio > self.min_wick_ratio and  # Long lower wick
                    upper_wick < body)  # Small upper wick
        else:
            # Bearish hammer (inverted hammer/hanging man): small body at bottom, long upper wick
            upper_wick = high - max(open_p, close)
            lower_wick = min(open_p, close) - low
            wick_ratio = upper_wick / total_range if total_range > 0 else 0
            
            return (close < open_p and  # Bearish
                    body_ratio < 0.3 and  # Small body
                    wick_ratio > self.min_wick_ratio and  # Long upper wick
                    lower_wick < body)  # Small lower wick
    
    def _is_engulfing(self, candles: list, idx: int, direction: str = "bullish") -> bool:
        """Check if candle at idx is an engulfing pattern."""
        if idx < 1 or idx >= len(candles):
            return False
        
        prev = candles[idx - 1]
        curr = candles[idx]
        
        prev_body = abs(prev.close - prev.open)
        curr_body = abs(curr.close - curr.open)
        
        if direction == "bullish":
            # Bullish engulfing: current bullish candle engulfs previous bearish candle
            return (curr.close > curr.open and  # Current bullish
                    prev.close < prev.open and  # Previous bearish
                    curr.open < prev.close and  # Engulfs
                    curr.close > prev.open and
                    curr_body > prev_body * self.engulfing_body_ratio)
        else:
            # Bearish engulfing: current bearish candle engulfs previous bullish candle
            return (curr.close < curr.open and  # Current bearish
                    prev.close > prev.open and  # Previous bullish
                    curr.open > prev.close and  # Engulfs
                    curr.close < prev.open and
                    curr_body > prev_body * self.engulfing_body_ratio)
    
    def _is_reversal_pattern(self, candles: list, idx: int, direction: str) -> bool:
        """Check for reversal candlestick patterns."""
        if idx >= len(candles):
            return False
        
        c = candles[idx]
        
        # Check for hammer
        if self._is_hammer(c.open, c.high, c.low, c.close, direction):
            return True
        
        # Check for engulfing
        if self._is_engulfing(candles, idx, direction):
            return True
        
        return False
    
    def on_candle(self, symbol: str, candle: dict) -> Optional[TradeSignal]:
        """
        Process candle and generate Quick Flip signals.
        
        Args:
            symbol: Trading symbol
            candle: Dict with OHLCV and history
        """
        history = candle.get('history')
        if not history:
            return None
        
        # Get enough candles for calculations
        candles = history.get_candles(50)
        if len(candles) < 10:
            return None
        
        # Initialize symbol state
        if symbol not in self._candle_count:
            self._candle_count[symbol] = 0
            self._range_confirmed[symbol] = False
        
        self._candle_count[symbol] += 1
        current_time = datetime.utcnow()
        
        # Step 1: ESTABLISH RANGE (first N bars = ~15m of data on 5m timeframe)
        if not self._range_confirmed.get(symbol, False):
            if self._candle_count[symbol] >= self.range_bars:
                # Calculate range from first N candles
                range_candles = candles[-self.range_bars:]
                self._range_high[symbol] = max(c.high for c in range_candles)
                self._range_low[symbol] = min(c.low for c in range_candles)
                self._range_time[symbol] = current_time
                
                # Calculate ATR of the range period
                range_atr = self._calculate_atr(range_candles, self.range_bars)
                self._range_atr[symbol] = range_atr
                
                # Check if it's a liquidity candle (large ATR compared to recent)
                recent_atr = self._calculate_atr(candles, 20)
                self._is_liquidity_candle[symbol] = range_atr > (recent_atr * self.atr_multiplier)
                
                self._range_confirmed[symbol] = True
                
                # Only proceed if it's a liquidity candle
                if not self._is_liquidity_candle[symbol]:
                    return None
            else:
                return None
        
        # Check if we've exceeded max wait time
        range_time = self._range_time.get(symbol)
        if range_time and (current_time - range_time) > timedelta(minutes=self.max_wait_minutes):
            # Reset range after 90 minutes - no valid reversal found
            self._range_confirmed[symbol] = False
            self._candle_count[symbol] = 0
            return None
        
        # Must be a liquidity candle to proceed
        if not self._is_liquidity_candle.get(symbol, False):
            return None
        
        range_high = self._range_high.get(symbol)
        range_low = self._range_low.get(symbol)
        if not range_high or not range_low:
            return None
        
        range_size = range_high - range_low
        
        # Get instrument multiplier for proper SL/TP scaling
        multiplier = self._get_atr_multiplier(symbol)
        adjusted_range_size = range_size * multiplier
        adjusted_sl_buffer = self.sl_buffer * multiplier
        
        # Get current/latest candle
        curr = candles[-1]
        prev = candles[-2] if len(candles) > 1 else curr
        
        # Step 2: LOOK FOR REVERSAL PATTERNS OUTSIDE THE BOX
        
        # LONG Setup: Price breaks below range low, then reversal
        if curr.low < range_low:
            # Check for bullish reversal pattern
            if self._is_reversal_pattern(candles, -1, "bullish"):
                # Entry: Above the reversal candle high
                entry = curr.high
                stop = curr.low - adjusted_sl_buffer
                target = entry + (adjusted_range_size * self.risk_reward)
                
                return self.create_signal(
                    symbol=symbol,
                    direction="LONG",
                    entry_price=entry,
                    stop_loss=stop,
                    take_profit=target,
                    confidence=0.72,
                    reason=f"QuickFlip: Liquidity sweep below box + bullish {self._get_pattern_name(candles, -1, 'bullish')}"
                )
        
        # SHORT Setup: Price breaks above range high, then reversal
        if curr.high > range_high:
            # Check for bearish reversal pattern
            if self._is_reversal_pattern(candles, -1, "bearish"):
                # Entry: Below the reversal candle low
                entry = curr.low
                stop = curr.high + adjusted_sl_buffer
                target = entry - (adjusted_range_size * self.risk_reward)
                
                return self.create_signal(
                    symbol=symbol,
                    direction="SHORT",
                    entry_price=entry,
                    stop_loss=stop,
                    take_profit=target,
                    confidence=0.72,
                    reason=f"QuickFlip: Liquidity sweep above box + bearish {self._get_pattern_name(candles, -1, 'bearish')}"
                )
        
        return None
    
    def _get_pattern_name(self, candles: list, idx: int, direction: str) -> str:
        """Get the name of the detected pattern."""
        if self._is_hammer(candles[idx].open, candles[idx].high, 
                          candles[idx].low, candles[idx].close, direction):
            return "hammer"
        if self._is_engulfing(candles, idx, direction):
            return "engulfing"
        return "reversal"
    
    def on_tick(self, symbol: str, price: float, timestamp: datetime) -> Optional[TradeSignal]:
        """Tick-based processing - not used for this candle-based strategy."""
        return None
