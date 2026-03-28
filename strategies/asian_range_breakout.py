"""
Asian Range Breakout Strategy - Range breakout at London open.

From Brain:
- Mark the high/low of the Asian session (00:00-08:00 UTC)
- Buy stop 2 pips above Asian high
- Sell stop 2 pips below Asian low
- Stop loss at middle of range
- Target 1:2 risk/reward
- Best on 1H or 4H chart
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy_loader import BaseStrategy
from indicators import Indicators
from datetime import datetime
from typing import Optional
from models import TradeSignal


class AsianRangeBreakoutStrategy(BaseStrategy):
    """
    Asian Range Breakout - trades the breakout of Asian session range at London open.
    
    Setup:
    - Track high/low during Asian session (00:00-08:00 UTC)
    - At London open (08:00 UTC), set breakout levels
    - Trade breakout above high (long) or below low (short)
    
    Best for: Forex majors (EURUSD, GBPUSD, USDJPY)
    """
    
    name = "AsianRangeBreakoutStrategy"
    symbols = None  # Uses all active symbols from feed_config.json
    
    def __init__(self, params: dict = None):
        super().__init__(params)
        
        self.ind = Indicators(max_history=100)
        
        # Asian session times (UTC)
        self.asian_start_hour = self.params.get("asian_start_hour", 0)
        self.asian_end_hour = self.params.get("asian_end_hour", 8)
        
        # London session (trading time)
        self.london_start_hour = self.params.get("london_start_hour", 8)
        self.london_end_hour = self.params.get("london_end_hour", 16)
        
        # Breakout buffer (pips)
        self.breakout_pips = self.params.get("breakout_pips", 2)
        self.pip_value = self.params.get("pip_value", 0.0001)  # For forex
        
        # Risk/reward
        self.risk_reward = self.params.get("risk_reward", 2.0)
        
        # Per-symbol state
        self.indicators = {}  # symbol -> Indicators
        self.asian_high = {}  # symbol -> float
        self.asian_low = {}  # symbol -> float
        self.range_set = {}  # symbol -> bool
        self.traded_today = {}  # symbol -> bool
        self.last_date = {}  # symbol -> date
        self.asian_prices = {}  # symbol -> List[float]
    
    def _init_symbol(self, symbol: str):
        """Initialize per-symbol state."""
        if symbol not in self.indicators:
            self.indicators[symbol] = Indicators(max_history=100)
            self.asian_high[symbol] = None
            self.asian_low[symbol] = None
            self.range_set[symbol] = False
            self.traded_today[symbol] = False
            self.last_date[symbol] = None
            self.asian_prices[symbol] = []
    
    def _is_asian_session(self, timestamp: datetime) -> bool:
        """Check if we're in Asian session."""
        return self.asian_start_hour <= timestamp.hour < self.asian_end_hour
    
    def _is_london_session(self, timestamp: datetime) -> bool:
        """Check if we're in London session (trading time)."""
        return self.london_start_hour <= timestamp.hour < self.london_end_hour
    
    def _reset_daily(self, symbol: str):
        """Reset for new trading day."""
        self.asian_high[symbol] = None
        self.asian_low[symbol] = None
        self.range_set[symbol] = False
        self.traded_today[symbol] = False
        self.asian_prices[symbol] = []
    
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
        
        # During Asian session - collect prices
        if self._is_asian_session(timestamp):
            self.asian_prices[symbol].append(price)
            return None
        
        # Set range at end of Asian session
        if not self.range_set[symbol] and self.asian_prices[symbol]:
            self.asian_high[symbol] = max(self.asian_prices[symbol])
            self.asian_low[symbol] = min(self.asian_prices[symbol])
            self.range_set[symbol] = True
            return None
        
        # Only trade during London session
        if not self.range_set[symbol] or not self._is_london_session(timestamp):
            return None
        
        # Calculate breakout levels
        buffer = self.breakout_pips * self.pip_value
        breakout_long = self.asian_high[symbol] + buffer
        breakout_short = self.asian_low[symbol] - buffer
        
        # Middle of range for stop loss
        range_middle = (self.asian_high[symbol] + self.asian_low[symbol]) / 2
        
        # Long breakout
        if price > breakout_long:
            self.traded_today[symbol] = True
            stop_loss = range_middle
            risk = price - stop_loss
            take_profit = price + (risk * self.risk_reward)
            
            return self.create_signal(
                symbol=symbol,
                direction="LONG",
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=0.7,
                reason=f"Asian range breakout above {self.asian_high[symbol]:.5f}"
            )
        
        # Short breakout
        if price < breakout_short:
            self.traded_today[symbol] = True
            stop_loss = range_middle
            risk = stop_loss - price
            take_profit = price - (risk * self.risk_reward)
            
            return self.create_signal(
                symbol=symbol,
                direction="SHORT",
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=0.7,
                reason=f"Asian range breakout below {self.asian_low[symbol]:.5f}"
            )
        
        return None
