"""
WardenWM Strategy - Warden WM Engulf Strategy
Wraps the WardenWM signal logic in a proper BaseStrategy class.
Supports 15m, 30m, and 60m timeframes.
"""
from strategy_loader import BaseStrategy
from models import TradeSignal, TradeDirection
from typing import Optional
import pandas as pd
from datetime import datetime

# Import the signal function from the original module
from strategies.WardenWM import get_warden_wm_signal_by_timeframe, WARDEN_WM_SETTINGS


# Map internal timeframe names to WardenWM timeframe names
TIMEFRAME_MAP = {
    "M15": "15m",
    "M30": "30m", 
    "H1": "60m",
}


class WardenWM(BaseStrategy):
    """
    Warden WM Engulf Strategy
    
    Trades bullish/bearish engulfing reversals with:
    - Full-bodied candle requirement
    - EMA context (20/200 magnet logic)
    - Anti stop-hunt sweep filters
    - Support/Resistance proximity filters
    - Minimum R:R requirements
    
    Supports M15, M30, H1 timeframes.
    """
    name = "WardenWM"
    symbols = None  # Use all active symbols
    timeframe = "M15"  # Primary timeframe
    timeframes = ["M15", "M30", "H1"]  # All supported timeframes
    max_positions = 0  # Unlimited total positions
    max_positions_per_symbol = 1  # One trade per symbol
    
    def __init__(self, params: dict = None):
        super().__init__(params)
    
    def on_candle(self, symbol: str, candle: dict) -> Optional[TradeSignal]:
        """
        Process new candle and generate signals.
        Automatically uses the correct timeframe settings.
        """
        history = candle.get('history')
        if not history:
            return None
        
        # Get candle timeframe
        candle_tf = candle.get('timeframe', 'M15')
        
        # Map to WardenWM timeframe format
        warden_tf = TIMEFRAME_MAP.get(candle_tf)
        if not warden_tf or warden_tf not in WARDEN_WM_SETTINGS:
            return None
        
        # Get last 250 candles for calculations
        candles = history.get_candles(250)
        if len(candles) < 220:
            return None
        
        # Convert to DataFrame for WardenWM
        df = pd.DataFrame({
            'open': [c.open for c in candles],
            'high': [c.high for c in candles],
            'low': [c.low for c in candles],
            'close': [c.close for c in candles],
        })
        
        # Get signal from WardenWM logic
        signal_data = get_warden_wm_signal_by_timeframe(df, warden_tf)
        
        if signal_data is None:
            return None
        
        # Convert WardenWM signal to TradeSignal
        direction_str = signal_data.get('direction', 'LONG')
        
        return self.create_signal(
            symbol=symbol,
            direction=direction_str,
            entry_price=signal_data['entry_price'],
            stop_loss=signal_data['stop_price'],
            take_profit=signal_data['target_price'],
            confidence=0.75,
            reason=f"WardenWM {candle_tf} {signal_data.get('signal_type')}: {signal_data.get('ema_context')} | RR={signal_data.get('rr', 0):.2f}",
            apply_multiplier=True
        )
    
    def on_tick(self, symbol: str, price: float, timestamp: datetime) -> Optional[TradeSignal]:
        """Tick-based processing - not used for this candle-based strategy."""
        return None
