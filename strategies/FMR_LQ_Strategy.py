"""
FMR-LQ Strategy - Fractal Magnet Reversal with Liquidity Qualification
Wraps the FMR-LQ signal logic in a proper BaseStrategy class.
Supports 15m, 30m, and 60m timeframes.
"""
from strategy_loader import BaseStrategy
from models import TradeSignal, TradeDirection
from typing import Optional, Dict
import pandas as pd
from datetime import datetime

# Import the signal function from the original module
# Note: FMR-LQ.py has a hyphen in the name, so we import directly
import importlib.util
import sys
from pathlib import Path

# Load FMR-LQ module directly (can't use standard import due to hyphen in filename)
fmr_lq_path = Path(__file__).parent / "FMR-LQ.py"
spec = importlib.util.spec_from_file_location("fmr_lq_module", fmr_lq_path)
fmr_lq_module = importlib.util.module_from_spec(spec)
sys.modules["fmr_lq_module"] = fmr_lq_module
spec.loader.exec_module(fmr_lq_module)
get_fmr_lq_signal = fmr_lq_module.get_fmr_lq_signal


# Timeframe-specific settings for FMR-LQ
FMR_LQ_SETTINGS = {
    "M15": {
        "timeframe": "15m",
        "stop_buffer": 0.0003,      # ~3 pips
        "max_sweep": 0.0005,        # ~5 pips
        "max_candle_size": 0.0020,  # ~20 pips
        "near_20_distance": 0.0005, # ~5 pips
    },
    "M30": {
        "timeframe": "30m",
        "stop_buffer": 0.0004,      # ~4 pips
        "max_sweep": 0.0006,        # ~6 pips
        "max_candle_size": 0.0025,  # ~25 pips
        "near_20_distance": 0.0006, # ~6 pips
    },
    "H1": {
        "timeframe": "60m",
        "stop_buffer": 0.0005,      # ~5 pips
        "max_sweep": 0.0008,        # ~8 pips
        "max_candle_size": 0.0035,  # ~35 pips
        "near_20_distance": 0.0008, # ~8 pips
    },
}


class FMR_LQ(BaseStrategy):
    """
    FMR-LQ (Fractal Magnet Reversal - Liquidity Qualified)
    
    Trades bullish/bearish engulfing reversals with:
    - EMA context (20/200 magnet logic)
    - Anti stop-hunt sweep filters  
    - Minimum R:R requirements
    - Strong close filters
    
    Supports M15, M30, H1 timeframes.
    """
    name = "FMR-LQ"
    symbols = None  # Use all active symbols
    timeframe = "M15"  # Primary timeframe
    timeframes = ["M15", "M30", "H1"]  # All supported timeframes
    max_positions = 0  # Unlimited total positions
    max_positions_per_symbol = 1  # One trade per symbol
    
    def __init__(self, params: dict = None):
        super().__init__(params)
        self.min_rr = params.get('min_rr', 1.0) if params else 1.0
        self.body_ratio_threshold = params.get('body_ratio_threshold', 0.90) if params else 0.90
    
    def on_candle(self, symbol: str, candle: dict) -> Optional[TradeSignal]:
        """
        Process new candle and generate signals across all timeframes.
        Returns the best valid signal found.
        """
        history = candle.get('history')
        if not history:
            return None
        
        # Get candle timeframe
        candle_tf = candle.get('timeframe', 'M15')
        
        # Check if this timeframe is supported
        if candle_tf not in FMR_LQ_SETTINGS:
            return None
        
        settings = FMR_LQ_SETTINGS[candle_tf]
        
        # Get enough candles for EMA200 calculation
        candles = history.get_candles(250)
        if len(candles) < 210:
            return None
        
        # Convert to DataFrame
        df = pd.DataFrame({
            'open': [c.open for c in candles],
            'high': [c.high for c in candles],
            'low': [c.low for c in candles],
            'close': [c.close for c in candles],
        })
        
        # Get signal with timeframe-specific settings
        signal_data = get_fmr_lq_signal(
            df=df,
            timeframe=settings["timeframe"],
            stop_buffer=settings["stop_buffer"],
            max_sweep=settings["max_sweep"],
            max_candle_size=settings["max_candle_size"],
            near_20_distance=settings["near_20_distance"],
            min_rr=self.min_rr,
            body_ratio_threshold=self.body_ratio_threshold,
            min_bull_close_position=0.80,
            max_bear_close_position=0.20,
        )
        
        if signal_data is None:
            return None
        
        # Convert to TradeSignal
        direction_str = signal_data.get('direction', 'LONG')
        
        return self.create_signal(
            symbol=symbol,
            direction=direction_str,
            entry_price=signal_data['entry_price'],
            stop_loss=signal_data['stop_price'],
            take_profit=signal_data['target_price'],
            confidence=0.7,
            reason=f"FMR-LQ {candle_tf} {signal_data.get('signal_type')}: {signal_data.get('target_type')} | RR={signal_data.get('rr', 0):.2f}",
            apply_multiplier=True
        )
    
    def on_tick(self, symbol: str, price: float, timestamp: datetime) -> Optional[TradeSignal]:
        """Tick-based processing - not used for this candle-based strategy."""
        return None
