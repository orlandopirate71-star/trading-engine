"""
Candle Aggregator - Converts tick data into time-based OHLC candles.

Supports multiple timeframes (1m, 5m, 15m, 1h, 4h, 1d).
Maintains candle history for indicator calculations.
Calls on_candle() on strategies when candles close.
"""
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum


class Timeframe(Enum):
    M1 = 60          # 1 minute
    M5 = 300         # 5 minutes
    M15 = 900        # 15 minutes
    M30 = 1800       # 30 minutes
    H1 = 3600        # 1 hour
    H4 = 14400       # 4 hours
    D1 = 86400       # 1 day


@dataclass
class Candle:
    """OHLC Candle."""
    symbol: str
    timeframe: Timeframe
    timestamp: datetime      # Candle open time
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    tick_count: int = 0
    closed: bool = False
    
    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe.name,
            "timestamp": self.timestamp.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "tick_count": self.tick_count,
            "closed": self.closed
        }


@dataclass
class CandleHistory:
    """Maintains candle history for a symbol/timeframe pair."""
    symbol: str
    timeframe: Timeframe
    max_candles: int = 500
    candles: List[Candle] = field(default_factory=list)
    current: Optional[Candle] = None
    
    def add_candle(self, candle: Candle):
        """Add a closed candle to history."""
        self.candles.append(candle)
        if len(self.candles) > self.max_candles:
            self.candles.pop(0)
    
    def get_closes(self, count: int = None) -> List[float]:
        """Get close prices."""
        candles = self.candles[-count:] if count else self.candles
        return [c.close for c in candles]
    
    def get_highs(self, count: int = None) -> List[float]:
        """Get high prices."""
        candles = self.candles[-count:] if count else self.candles
        return [c.high for c in candles]
    
    def get_lows(self, count: int = None) -> List[float]:
        """Get low prices."""
        candles = self.candles[-count:] if count else self.candles
        return [c.low for c in candles]
    
    def get_opens(self, count: int = None) -> List[float]:
        """Get open prices."""
        candles = self.candles[-count:] if count else self.candles
        return [c.open for c in candles]
    
    def get_volumes(self, count: int = None) -> List[float]:
        """Get volumes."""
        candles = self.candles[-count:] if count else self.candles
        return [c.volume for c in candles]
    
    def get_candles(self, count: int = None) -> List[Candle]:
        """Get candle objects."""
        return self.candles[-count:] if count else self.candles.copy()
    
    def __len__(self):
        return len(self.candles)


class CandleAggregator:
    """
    Aggregates tick data into time-based OHLC candles.
    
    Usage:
        aggregator = CandleAggregator(timeframes=[Timeframe.M1, Timeframe.M5])
        aggregator.on_candle_close = my_callback
        
        # Feed ticks
        aggregator.on_tick("EURUSD", 1.1234, volume=100)
    """
    
    def __init__(
        self,
        timeframes: List[Timeframe] = None,
        max_history: int = 500
    ):
        self.timeframes = timeframes or [Timeframe.M1, Timeframe.M5, Timeframe.M15, Timeframe.H1]
        self.max_history = max_history
        
        # History per symbol per timeframe
        # {symbol: {timeframe: CandleHistory}}
        self.history: Dict[str, Dict[Timeframe, CandleHistory]] = defaultdict(dict)
        
        # Callbacks
        self.on_candle_close: Optional[Callable[[Candle, CandleHistory], None]] = None
        self._candle_close_callbacks: List[Callable[[Candle, CandleHistory], None]] = []
        
        # Thread safety
        self._lock = threading.Lock()
        
        print(f"[CandleAggregator] Initialized with timeframes: {[tf.name for tf in self.timeframes]}")

    def add_candle_callback(self, callback: Callable[[Candle, CandleHistory], None]):
        """Register an additional callback for candle close events."""
        self._candle_close_callbacks.append(callback)

    def _get_candle_start(self, timestamp: datetime, timeframe: Timeframe) -> datetime:
        """Get the start time of the candle containing this timestamp."""
        seconds = timeframe.value
        
        # Truncate to candle boundary
        ts = timestamp.timestamp()
        candle_ts = (ts // seconds) * seconds
        return datetime.fromtimestamp(candle_ts)
    
    def _get_or_create_history(self, symbol: str, timeframe: Timeframe) -> CandleHistory:
        """Get or create candle history for symbol/timeframe."""
        if timeframe not in self.history[symbol]:
            self.history[symbol][timeframe] = CandleHistory(
                symbol=symbol,
                timeframe=timeframe,
                max_candles=self.max_history
            )
        return self.history[symbol][timeframe]
    
    def on_tick(
        self,
        symbol: str,
        price: float,
        volume: float = 0.0,
        timestamp: datetime = None
    ):
        """
        Process a tick and update candles.
        
        Args:
            symbol: Trading symbol
            price: Tick price
            volume: Tick volume (optional)
            timestamp: Tick timestamp (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        
        with self._lock:
            for timeframe in self.timeframes:
                self._update_candle(symbol, price, volume, timestamp, timeframe)
    
    def _update_candle(
        self,
        symbol: str,
        price: float,
        volume: float,
        timestamp: datetime,
        timeframe: Timeframe
    ):
        """Update candle for a specific timeframe."""
        history = self._get_or_create_history(symbol, timeframe)
        candle_start = self._get_candle_start(timestamp, timeframe)
        
        # Check if we need to close current candle and start new one
        if history.current is not None:
            if candle_start > history.current.timestamp:
                # Close current candle
                history.current.closed = True
                history.add_candle(history.current)

                # Trigger callbacks
                if self.on_candle_close:
                    try:
                        self.on_candle_close(history.current, history)
                    except Exception as e:
                        print(f"[CandleAggregator] Callback error: {e}")
                for cb in self._candle_close_callbacks:
                    try:
                        cb(history.current, history)
                    except Exception as e:
                        print(f"[CandleAggregator] Callback error: {e}")

                # Start new candle
                history.current = None
        
        # Create new candle if needed
        if history.current is None:
            history.current = Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=candle_start,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=volume,
                tick_count=1
            )
        else:
            # Update current candle
            history.current.high = max(history.current.high, price)
            history.current.low = min(history.current.low, price)
            history.current.close = price
            history.current.volume += volume
            history.current.tick_count += 1
    
    def get_history(self, symbol: str, timeframe: Timeframe) -> Optional[CandleHistory]:
        """Get candle history for symbol/timeframe."""
        with self._lock:
            return self.history.get(symbol, {}).get(timeframe)
    
    def get_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        count: int = None
    ) -> List[Candle]:
        """Get closed candles for symbol/timeframe."""
        history = self.get_history(symbol, timeframe)
        if history:
            return history.get_candles(count)
        return []
    
    def get_current_candle(self, symbol: str, timeframe: Timeframe) -> Optional[Candle]:
        """Get the current (unclosed) candle."""
        history = self.get_history(symbol, timeframe)
        if history:
            return history.current
        return None
    
    def get_closes(self, symbol: str, timeframe: Timeframe, count: int = None) -> List[float]:
        """Get close prices for symbol/timeframe."""
        history = self.get_history(symbol, timeframe)
        if history:
            return history.get_closes(count)
        return []
    
    def get_highs(self, symbol: str, timeframe: Timeframe, count: int = None) -> List[float]:
        """Get high prices for symbol/timeframe."""
        history = self.get_history(symbol, timeframe)
        if history:
            return history.get_highs(count)
        return []
    
    def get_lows(self, symbol: str, timeframe: Timeframe, count: int = None) -> List[float]:
        """Get low prices for symbol/timeframe."""
        history = self.get_history(symbol, timeframe)
        if history:
            return history.get_lows(count)
        return []
    
    def get_ohlc(
        self,
        symbol: str,
        timeframe: Timeframe,
        count: int = None
    ) -> Dict[str, List[float]]:
        """Get OHLC data as dict of lists."""
        history = self.get_history(symbol, timeframe)
        if history:
            candles = history.get_candles(count)
            return {
                "open": [c.open for c in candles],
                "high": [c.high for c in candles],
                "low": [c.low for c in candles],
                "close": [c.close for c in candles],
                "volume": [c.volume for c in candles],
                "timestamp": [c.timestamp for c in candles]
            }
        return {"open": [], "high": [], "low": [], "close": [], "volume": [], "timestamp": []}
    
    def get_status(self) -> dict:
        """Get aggregator status."""
        with self._lock:
            status = {
                "timeframes": [tf.name for tf in self.timeframes],
                "symbols": {}
            }
            
            for symbol, timeframes in self.history.items():
                status["symbols"][symbol] = {}
                for tf, history in timeframes.items():
                    status["symbols"][symbol][tf.name] = {
                        "candle_count": len(history),
                        "current_candle": history.current.to_dict() if history.current else None
                    }
            
            return status


# Singleton
_aggregator: Optional[CandleAggregator] = None


def get_candle_aggregator(
    timeframes: List[Timeframe] = None,
    max_history: int = 500
) -> CandleAggregator:
    """Get or create the candle aggregator singleton."""
    global _aggregator
    if _aggregator is None:
        _aggregator = CandleAggregator(timeframes, max_history)
    return _aggregator
