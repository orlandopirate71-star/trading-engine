"""
One-Candle Daily Strategy - Time-based breakout on US market open.

From Brain:
- Mark the high/low of the 9:30 AM New York market open candle
- Trade breakout above high (long) or below low (short)
- Stop on the opposite side of the candle
- Target 1R-2R
- Best on US indices (NASDAQ, S&P 500, Dow)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy_loader import BaseStrategy
from indicators import Indicators
from datetime import datetime, time
from typing import Optional
from models import TradeSignal


class OneCandleDailyStrategy(BaseStrategy):
    """
    Time-based breakout strategy on US market open.
    
    Setup:
    - Wait for the 9:30 AM NY opening candle to complete (1-min or 5-min)
    - Mark the high and low of that candle
    - Trade breakout above high (long) or below low (short)
    
    Best for: US indices, high-volume stocks
    """
    
    name = "OneCandleDailyStrategy"
    symbols = None  # Uses all active symbols from feed_config.json
    
    def __init__(self, params: dict = None):
        super().__init__(params)
        
        # Per-symbol state
        self.indicators = {}  # symbol -> Indicators
        self.opening_high = {}  # symbol -> float
        self.opening_low = {}  # symbol -> float
        self.candle_set = {}  # symbol -> bool
        self.traded_today = {}  # symbol -> bool
        self.last_date = {}  # symbol -> date
        self.candle_prices = {}  # symbol -> List[float]
        self.candle_start_time = {}  # symbol -> datetime
        
        # Candle formation period (minutes after 9:30)
        self.candle_minutes = self.params.get("candle_minutes", 5)
        
        # NY market open time (9:30 AM ET = 14:30 UTC)
        self.market_open_hour = self.params.get("market_open_hour", 14)
        self.market_open_minute = self.params.get("market_open_minute", 30)
        
        # Breakout buffer (pips/points above/below)
        self.breakout_buffer = self.params.get("breakout_buffer", 2)
        
        # Risk/reward
        self.risk_reward = self.params.get("risk_reward", 2.0)
    
    def _init_symbol(self, symbol: str):
        """Initialize per-symbol state."""
        if symbol not in self.indicators:
            self.indicators[symbol] = Indicators(max_history=100)
            self.opening_high[symbol] = None
            self.opening_low[symbol] = None
            self.candle_set[symbol] = False
            self.traded_today[symbol] = False
            self.last_date[symbol] = None
            self.candle_prices[symbol] = []
            self.candle_start_time[symbol] = None
    
    def _is_market_open_time(self, timestamp: datetime) -> bool:
        """Check if we're at market open."""
        return (timestamp.hour == self.market_open_hour and 
                timestamp.minute >= self.market_open_minute and
                timestamp.minute < self.market_open_minute + self.candle_minutes)
    
    def _is_trading_time(self, timestamp: datetime) -> bool:
        """Check if we're in trading hours (after opening candle)."""
        if timestamp.hour == self.market_open_hour:
            return timestamp.minute >= self.market_open_minute + self.candle_minutes
        return timestamp.hour > self.market_open_hour and timestamp.hour < 21  # Until 9 PM UTC
    
    def _reset_daily(self, symbol: str):
        """Reset for new trading day."""
        self.opening_high[symbol] = None
        self.opening_low[symbol] = None
        self.candle_set[symbol] = False
        self.traded_today[symbol] = False
        self.candle_prices[symbol] = []
        self.candle_start_time[symbol] = None
    
    def on_tick(self, symbol: str, price: float, timestamp: datetime) -> Optional[TradeSignal]:
        self._init_symbol(symbol)
        self.indicators[symbol].add(price)
        
        # Reset on new day
        current_date = timestamp.date()
        if self.last_date[symbol] != current_date:
            self._reset_daily(symbol)
            self.last_date[symbol] = current_date
        
        # Already traded today
        if self.traded_today[symbol]:
            return None
        
        # During opening candle formation - collect prices
        if self._is_market_open_time(timestamp):
            if self.candle_start_time[symbol] is None:
                self.candle_start_time[symbol] = timestamp
            self.candle_prices[symbol].append(price)
            return None
        
        # Set opening candle high/low after formation period
        if not self.candle_set[symbol] and self.candle_prices[symbol]:
            self.opening_high[symbol] = max(self.candle_prices[symbol])
            self.opening_low[symbol] = min(self.candle_prices[symbol])
            self.candle_set[symbol] = True
            return None
        
        # Not in trading time or candle not set
        if not self.candle_set[symbol] or not self._is_trading_time(timestamp):
            return None
        
        # Calculate levels with buffer
        candle_range = self.opening_high[symbol] - self.opening_low[symbol]
        breakout_long = self.opening_high[symbol] + self.breakout_buffer
        breakout_short = self.opening_low[symbol] - self.breakout_buffer
        
        # Long breakout
        if price > breakout_long:
            self.traded_today[symbol] = True
            stop_loss = self.opening_low[symbol] - self.breakout_buffer
            risk = price - stop_loss
            take_profit = price + (risk * self.risk_reward)
            
            return self.create_signal(
                symbol=symbol,
                direction="LONG",
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=0.7,
                reason=f"Opening candle breakout above {self.opening_high[symbol]:.2f}"
            )
        
        # Short breakout
        if price < breakout_short:
            self.traded_today[symbol] = True
            stop_loss = self.opening_high[symbol] + self.breakout_buffer
            risk = stop_loss - price
            take_profit = price - (risk * self.risk_reward)
            
            return self.create_signal(
                symbol=symbol,
                direction="SHORT",
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=0.7,
                reason=f"Opening candle breakout below {self.opening_low[symbol]:.2f}"
            )
        
        return None


# Alias for strategy loader
OneCandleDaily = OneCandleDailyStrategy
