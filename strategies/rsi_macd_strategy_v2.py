"""
RSI + MACD Strategy V2 - Improved version with better signal logic and risk management.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy_loader import BaseStrategy
from indicators import Indicators
from datetime import datetime
from typing import Optional
from models import TradeSignal


class RSIMACDStrategyV2(BaseStrategy):
    """
    Improved RSI + MACD strategy:
    - RSI for overbought/oversold conditions (relaxed thresholds)
    - MACD for momentum confirmation (any positive/negative momentum)
    - Bollinger Bands for volatility context
    - ADX filter to avoid choppy markets
    - Dynamic take profit targeting BB middle
    
    Long Entry:
    - RSI < 40 (oversold, more relaxed)
    - MACD histogram positive and increasing
    - Price near lower Bollinger Band (within 40%)
    - ADX > 15 (some trend present)
    
    Short Entry:
    - RSI > 60 (overbought, more relaxed)
    - MACD histogram negative and decreasing
    - Price near upper Bollinger Band (within 40%)
    - ADX > 15 (some trend present)
    """
    
    name = "RSIMACDStrategyV2"
    
    def __init__(self, params: dict = None):
        super().__init__(params)
        
        # Per-symbol state
        self.indicators = {}
        self.last_signal_time = {}
        self.prev_macd_hist = {}
        
        # Parameters - More relaxed for forex
        self.rsi_period = self.params.get("rsi_period", 14)
        self.rsi_oversold = self.params.get("rsi_oversold", 40)  # More relaxed
        self.rsi_overbought = self.params.get("rsi_overbought", 60)  # More relaxed
        self.bb_period = self.params.get("bb_period", 20)
        self.bb_std = self.params.get("bb_std", 2.0)
        self.bb_distance_threshold = self.params.get("bb_distance_threshold", 0.4)  # 40% from band
        
        # ADX filter to avoid choppy markets
        self.adx_period = self.params.get("adx_period", 14)
        self.min_adx = self.params.get("min_adx", 15)  # Minimum trend strength
        
        # Risk management - Dynamic TP
        self.stop_loss_pct = self.params.get("stop_loss_pct", 0.015)  # 1.5% (tighter)
        self.use_dynamic_tp = self.params.get("use_dynamic_tp", True)  # Target BB middle
        self.fixed_tp_pct = self.params.get("fixed_tp_pct", 0.03)  # 3% if not using dynamic
        
        # Cooldown - Longer to avoid overtrading
        self.cooldown_minutes = self.params.get("cooldown_minutes", 5)
    
    def on_tick(self, symbol: str, price: float, timestamp: datetime) -> Optional[TradeSignal]:
        # Initialize per-symbol state
        if symbol not in self.indicators:
            self.indicators[symbol] = Indicators(max_history=200)
            self.prev_macd_hist[symbol] = None
        
        # Check cooldown
        if symbol in self.last_signal_time:
            time_since_signal = (timestamp - self.last_signal_time[symbol]).total_seconds() / 60
            if time_since_signal < self.cooldown_minutes:
                return None
        
        # Add price to indicator calculator
        self.indicators[symbol].add(price)
        
        # Need enough data
        if self.indicators[symbol].count < 50:
            return None
        
        # Calculate indicators
        rsi = self.indicators[symbol].rsi(self.rsi_period)
        macd_line, signal_line, macd_hist = self.indicators[symbol].macd()
        upper_bb, middle_bb, lower_bb = self.indicators[symbol].bollinger_bands(self.bb_period, self.bb_std)
        adx = self.indicators[symbol].adx(self.adx_period)
        
        if None in (rsi, macd_hist, upper_bb, adx):
            return None
        
        # Filter out choppy markets
        if adx < self.min_adx:
            return None
        
        # Track MACD histogram momentum (not just zero crossings)
        prev_hist = self.prev_macd_hist[symbol]
        macd_momentum_up = macd_hist > 0 and (prev_hist is None or macd_hist > prev_hist)
        macd_momentum_down = macd_hist < 0 and (prev_hist is None or macd_hist < prev_hist)
        self.prev_macd_hist[symbol] = macd_hist
        
        # Calculate distance from Bollinger Bands
        bb_range = upper_bb - lower_bb
        if bb_range == 0:
            return None
            
        dist_from_lower = (price - lower_bb) / bb_range
        dist_from_upper = (upper_bb - price) / bb_range
        
        # Long signal: RSI oversold + MACD momentum up + near lower BB + trending
        if rsi < self.rsi_oversold and macd_momentum_up and dist_from_lower < self.bb_distance_threshold:
            self.last_signal_time[symbol] = timestamp
            
            # Dynamic TP: target BB middle for mean reversion
            if self.use_dynamic_tp:
                take_profit = middle_bb
                # Ensure TP is above entry for longs
                if take_profit <= price:
                    take_profit = price * (1 + self.fixed_tp_pct)
            else:
                take_profit = price * (1 + self.fixed_tp_pct)
            
            stop_loss = price * (1 - self.stop_loss_pct)
            
            # Calculate actual R:R
            risk = price - stop_loss
            reward = take_profit - price
            rr_ratio = reward / risk if risk > 0 else 0
            
            # Only take trades with at least 1.5:1 R:R
            if rr_ratio < 1.5:
                return None
            
            # Confidence based on multiple factors
            rsi_strength = (self.rsi_oversold - rsi) / self.rsi_oversold  # 0 to 1
            bb_strength = (self.bb_distance_threshold - dist_from_lower) / self.bb_distance_threshold  # 0 to 1
            macd_strength = min(abs(macd_hist) * 100, 1.0)  # Normalize MACD
            adx_strength = min((adx - self.min_adx) / 20, 1.0)  # 0 to 1
            
            confidence = 0.55 + (rsi_strength * 0.15) + (bb_strength * 0.1) + (macd_strength * 0.1) + (adx_strength * 0.1)
            
            return self.create_signal(
                symbol=symbol,
                direction="LONG",
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=min(0.95, confidence),
                reason=f"RSI={rsi:.1f}, MACD+={macd_hist:.5f}, BB={dist_from_lower*100:.0f}%, ADX={adx:.1f}, RR={rr_ratio:.2f}"
            )
        
        # Short signal: RSI overbought + MACD momentum down + near upper BB + trending
        if rsi > self.rsi_overbought and macd_momentum_down and dist_from_upper < self.bb_distance_threshold:
            self.last_signal_time[symbol] = timestamp
            
            # Dynamic TP: target BB middle for mean reversion
            if self.use_dynamic_tp:
                take_profit = middle_bb
                # Ensure TP is below entry for shorts
                if take_profit >= price:
                    take_profit = price * (1 - self.fixed_tp_pct)
            else:
                take_profit = price * (1 - self.fixed_tp_pct)
            
            stop_loss = price * (1 + self.stop_loss_pct)
            
            # Calculate actual R:R
            risk = stop_loss - price
            reward = price - take_profit
            rr_ratio = reward / risk if risk > 0 else 0
            
            # Only take trades with at least 1.5:1 R:R
            if rr_ratio < 1.5:
                return None
            
            # Confidence based on multiple factors
            rsi_strength = (rsi - self.rsi_overbought) / (100 - self.rsi_overbought)  # 0 to 1
            bb_strength = (self.bb_distance_threshold - dist_from_upper) / self.bb_distance_threshold  # 0 to 1
            macd_strength = min(abs(macd_hist) * 100, 1.0)  # Normalize MACD
            adx_strength = min((adx - self.min_adx) / 20, 1.0)  # 0 to 1
            
            confidence = 0.55 + (rsi_strength * 0.15) + (bb_strength * 0.1) + (macd_strength * 0.1) + (adx_strength * 0.1)
            
            return self.create_signal(
                symbol=symbol,
                direction="SHORT",
                entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=min(0.95, confidence),
                reason=f"RSI={rsi:.1f}, MACD-={macd_hist:.5f}, BB={dist_from_upper*100:.0f}%, ADX={adx:.1f}, RR={rr_ratio:.2f}"
            )
        
        return None
