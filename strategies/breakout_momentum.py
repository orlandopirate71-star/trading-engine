"""
Breakout Momentum Strategy - Trades breakouts with volume and momentum confirmation.
Catches strong directional moves when price breaks key levels.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy_loader import BaseStrategy
from indicators import Indicators
from datetime import datetime
from typing import Optional
from models import TradeSignal


class BreakoutMomentumStrategy(BaseStrategy):
    """
    Breakout strategy with momentum confirmation:
    - Identifies support/resistance levels from recent highs/lows
    - Waits for price to break above/below with strong momentum
    - Uses ATR for dynamic stop loss and take profit
    - Confirms with volume increase (if available)
    
    Long Entry:
    - Price breaks above recent high
    - RSI > 50 (momentum confirmation)
    - ADX > 25 (trending market)
    
    Short Entry:
    - Price breaks below recent low
    - RSI < 50 (momentum confirmation)
    - ADX > 25 (trending market)
    """
    
    name = "BreakoutMomentumStrategy"
    
    def __init__(self, params: dict = None):
        super().__init__(params)
        
        # Per-symbol state
        self.indicators = {}
        self.last_signal_time = {}
        self.recent_high = {}
        self.recent_low = {}
        
        # Parameters
        self.lookback_period = self.params.get("lookback_period", 20)  # Period to find highs/lows
        self.breakout_threshold = self.params.get("breakout_threshold", 0.0005)  # 0.05% above/below
        self.rsi_period = self.params.get("rsi_period", 14)
        self.adx_period = self.params.get("adx_period", 14)
        self.adx_threshold = self.params.get("adx_threshold", 20)  # Minimum ADX for trending
        
        # Risk management - ATR-based
        self.atr_period = self.params.get("atr_period", 14)
        self.stop_loss_atr = self.params.get("stop_loss_atr", 2.0)  # 2x ATR for stop
        self.take_profit_atr = self.params.get("take_profit_atr", 3.0)  # 3x ATR for target (1.5:1 R:R)

        # Cooldown
        self.cooldown_minutes = self.params.get("cooldown_minutes", 5)
    
    def on_tick(self, symbol: str, price: float, timestamp: datetime) -> Optional[TradeSignal]:
        # Initialize per-symbol state
        if symbol not in self.indicators:
            self.indicators[symbol] = Indicators(max_history=200)
            self.recent_high[symbol] = price
            self.recent_low[symbol] = price
        
        # Check cooldown
        if symbol in self.last_signal_time:
            time_since_signal = (timestamp - self.last_signal_time[symbol]).total_seconds() / 60
            if time_since_signal < self.cooldown_minutes:
                return None
        
        # Add price to indicator calculator
        self.indicators[symbol].add(price)
        
        # Need enough data
        if self.indicators[symbol].count < max(self.lookback_period, 50):
            return None
        
        # Update recent high/low
        recent_prices = list(self.indicators[symbol].prices)[-self.lookback_period:]
        self.recent_high[symbol] = max(recent_prices)
        self.recent_low[symbol] = min(recent_prices)
        
        # Calculate indicators
        rsi = self.indicators[symbol].rsi(self.rsi_period)
        adx = self.indicators[symbol].adx(self.adx_period)
        atr = self.indicators[symbol].atr(self.atr_period)
        
        if None in (rsi, adx, atr) or atr == 0:
            return None
        
        # Only trade in trending markets
        if adx < self.adx_threshold:
            return None
        
        # Calculate breakout levels
        breakout_high = self.recent_high[symbol] * (1 + self.breakout_threshold)
        breakout_low = self.recent_low[symbol] * (1 - self.breakout_threshold)
        
        # Long signal: Breakout above recent high with bullish momentum
        if price > breakout_high and rsi > 50:
            self.last_signal_time[symbol] = timestamp
            
            # ATR-based stops
            stop_loss = price - (atr * self.stop_loss_atr)
            take_profit = price + (atr * self.take_profit_atr)
            
            # Confidence based on momentum strength
            momentum_strength = (rsi - 50) / 50  # 0 to 1
            trend_strength = min((adx - self.adx_threshold) / 20, 1.0)  # 0 to 1
            confidence = 0.6 + (momentum_strength * 0.2) + (trend_strength * 0.2)
            
            return self.create_signal(
                symbol=symbol,
                direction="LONG",
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=min(0.95, confidence),
                reason=f"Breakout above {self.recent_high[symbol]:.5f}, RSI={rsi:.1f}, ADX={adx:.1f}, ATR={atr:.5f}"
            )
        
        # Short signal: Breakout below recent low with bearish momentum
        if price < breakout_low and rsi < 50:
            self.last_signal_time[symbol] = timestamp
            
            # ATR-based stops
            stop_loss = price + (atr * self.stop_loss_atr)
            take_profit = price - (atr * self.take_profit_atr)
            
            # Confidence based on momentum strength
            momentum_strength = (50 - rsi) / 50  # 0 to 1
            trend_strength = min((adx - self.adx_threshold) / 20, 1.0)  # 0 to 1
            confidence = 0.6 + (momentum_strength * 0.2) + (trend_strength * 0.2)
            
            return self.create_signal(
                symbol=symbol,
                direction="SHORT",
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=min(0.95, confidence),
                reason=f"Breakout below {self.recent_low[symbol]:.5f}, RSI={rsi:.1f}, ADX={adx:.1f}, ATR={atr:.5f}"
            )
        
        return None
