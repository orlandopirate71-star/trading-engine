# ==========================================
# WardenWM.py
# ------------------------------------------
# Warden WM Engulf Strategy
#
# Strategy idea:
# - Trade bullish / bearish engulfing reversals
# - Prefer full-bodied candles
# - Candle should close strong in the direction of the move
# - Setup should either:
#   1) Start far from the 20 EMA and move back toward the 20 EMA
#   OR
#   2) Start on / near the 20 EMA and move toward the 200 EMA
# - Use a small prior-candle sweep only (anti stop-hunt filter)
# - Allow "almost same size" body as long as the current candle
#   is at least similar in size and directionally dominant
# - Optional simple support / resistance proximity filter
#
# NOTES:
# - This file assumes you already have candle DataFrames
# - Candle columns required:
#     open, high, low, close
# - This code only uses CLOSED candles
# - No trade manager included
#
# Author: ChatGPT (for Col)
# ==========================================

from typing import Dict, Optional, List
import pandas as pd
import numpy as np


# ==========================================
# STRATEGY SETTINGS BY TIMEFRAME
# ------------------------------------------
# These are starter values only.
# Tune them after demo testing.
# ==========================================

WARDEN_WM_SETTINGS = {
    "15m": {
        "stop_buffer": 0.0003,
        "max_sweep": 0.0004,
        "max_candle_size": 0.0018,
        "near_20_distance": 0.0004,
        "min_rr": 1.0,
        "body_ratio_threshold": 0.90,
        "min_bull_close_position": 0.80,
        "max_bear_close_position": 0.20,
        "full_body_min_ratio": 0.60,
        "sr_lookback": 20,
        "sr_tolerance": 0.0008,
    },

    "30m": {
        "stop_buffer": 0.0003,
        "max_sweep": 0.0005,
        "max_candle_size": 0.0025,
        "near_20_distance": 0.0005,
        "min_rr": 1.0,
        "body_ratio_threshold": 0.90,
        "min_bull_close_position": 0.80,
        "max_bear_close_position": 0.20,
        "full_body_min_ratio": 0.60,
        "sr_lookback": 20,
        "sr_tolerance": 0.0010,
    },

    "60m": {
        "stop_buffer": 0.0004,
        "max_sweep": 0.0006,
        "max_candle_size": 0.0035,
        "near_20_distance": 0.0007,
        "min_rr": 1.0,
        "body_ratio_threshold": 0.90,
        "min_bull_close_position": 0.80,
        "max_bear_close_position": 0.20,
        "full_body_min_ratio": 0.60,
        "sr_lookback": 20,
        "sr_tolerance": 0.0015,
    },
}


# ==========================================
# BASIC HELPERS
# ==========================================

def get_warden_wm_settings(timeframe: str) -> dict:
    """
    Return settings for the given timeframe.

    Supported:
    - 15m
    - 30m
    - 60m
    """
    if timeframe not in WARDEN_WM_SETTINGS:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return WARDEN_WM_SETTINGS[timeframe]


def validate_dataframe(df: pd.DataFrame) -> None:
    """
    Ensure the DataFrame contains the required candle columns.
    """
    required_cols = {"open", "high", "low", "close"}
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")


def add_emas(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return a copy of df with EMA20 and EMA200 columns added.
    """
    out = df.copy()
    out["ema20"] = out["close"].ewm(span=20, adjust=False).mean()
    out["ema200"] = out["close"].ewm(span=200, adjust=False).mean()
    return out


def candle_range(candle: pd.Series) -> float:
    """
    Full candle range = high - low
    """
    return float(candle["high"] - candle["low"])


def candle_body(candle: pd.Series) -> float:
    """
    Candle body = abs(close - open)
    """
    return float(abs(candle["close"] - candle["open"]))


def candle_body_ratio(candle: pd.Series) -> float:
    """
    Body ratio = body / full range
    Used to identify "full-bodied" candles.
    """
    rng = candle_range(candle)
    if rng <= 0:
        return 0.0
    return candle_body(candle) / rng


def close_position_in_range(candle: pd.Series) -> float:
    """
    Returns where the close sits inside the candle range:
    - 0.0 = close at low
    - 1.0 = close at high

    For bullish candles, strong close should be near 1.0
    For bearish candles, strong close should be near 0.0
    """
    rng = candle_range(candle)
    if rng <= 0:
        return 0.5
    return float((candle["close"] - candle["low"]) / rng)


def is_bullish(candle: pd.Series) -> bool:
    """
    True if candle closes above open.
    """
    return candle["close"] > candle["open"]


def is_bearish(candle: pd.Series) -> bool:
    """
    True if candle closes below open.
    """
    return candle["close"] < candle["open"]


# ==========================================
# SUPPORT / RESISTANCE HELPERS
# ------------------------------------------
# Simple "recent swing area" approximation:
# - resistance = highest high over lookback bars before signal candle
# - support    = lowest low over lookback bars before signal candle
# ==========================================

def get_recent_resistance(df: pd.DataFrame, end_index: int, lookback: int) -> Optional[float]:
    """
    Highest high in the lookback window BEFORE end_index.
    """
    start = max(0, end_index - lookback)
    if start >= end_index:
        return None
    return float(df.iloc[start:end_index]["high"].max())


def get_recent_support(df: pd.DataFrame, end_index: int, lookback: int) -> Optional[float]:
    """
    Lowest low in the lookback window BEFORE end_index.
    """
    start = max(0, end_index - lookback)
    if start >= end_index:
        return None
    return float(df.iloc[start:end_index]["low"].min())


def is_near_level(price: float, level: Optional[float], tolerance: float) -> bool:
    """
    Check if price is near a support / resistance level.
    """
    if level is None:
        return False
    return abs(price - level) <= tolerance


# ==========================================
# ENGULFING PATTERN HELPERS
# ------------------------------------------
# "Almost same size" logic included:
# - current body must be >= threshold * previous body
# - current body direction must dominate
# - not necessarily a textbook perfect engulf
# ==========================================

def is_bullish_engulfing(
    prev_candle: pd.Series,
    curr_candle: pd.Series,
    body_ratio_threshold: float = 0.90,
) -> bool:
    """
    Bullish engulfing / near-engulfing logic:
    - Previous candle bearish
    - Current candle bullish
    - Current body is at least similar in size to previous body
    - Current close pushes above previous open
    - Current open is at or below previous close (or very near in practice)
    """
    if not is_bearish(prev_candle):
        return False

    if not is_bullish(curr_candle):
        return False

    prev_body = candle_body(prev_candle)
    curr_body = candle_body(curr_candle)

    if prev_body <= 0:
        return False

    # Allow "almost same size" but current should be at least similar
    if curr_body < (prev_body * body_ratio_threshold):
        return False

    # Directional dominance / near textbook engulf
    if curr_candle["close"] <= prev_candle["open"]:
        return False

    if curr_candle["open"] > prev_candle["close"]:
        return False

    return True


def is_bearish_engulfing(
    prev_candle: pd.Series,
    curr_candle: pd.Series,
    body_ratio_threshold: float = 0.90,
) -> bool:
    """
    Bearish engulfing / near-engulfing logic:
    - Previous candle bullish
    - Current candle bearish
    - Current body is at least similar in size to previous body
    - Current close pushes below previous open
    - Current open is at or above previous close
    """
    if not is_bullish(prev_candle):
        return False

    if not is_bearish(curr_candle):
        return False

    prev_body = candle_body(prev_candle)
    curr_body = candle_body(curr_candle)

    if prev_body <= 0:
        return False

    # Allow "almost same size"
    if curr_body < (prev_body * body_ratio_threshold):
        return False

    # Directional dominance / near textbook engulf
    if curr_candle["close"] >= prev_candle["open"]:
        return False

    if curr_candle["open"] < prev_candle["close"]:
        return False

    return True


# ==========================================
# ANTI STOP-HUNT FILTER
# ------------------------------------------
# Your rule:
# - price must only just be above / below previous candle
# - avoid massive liquidity sweeps
# ==========================================

def bullish_small_sweep(prev_candle: pd.Series, curr_candle: pd.Series, max_sweep: float) -> bool:
    """
    For bullish reversal:
    - Current low should dip slightly below previous low
    - But not too far
    """
    if curr_candle["low"] >= prev_candle["low"]:
        return False

    sweep = prev_candle["low"] - curr_candle["low"]
    return sweep <= max_sweep


def bearish_small_sweep(prev_candle: pd.Series, curr_candle: pd.Series, max_sweep: float) -> bool:
    """
    For bearish reversal:
    - Current high should poke slightly above previous high
    - But not too far
    """
    if curr_candle["high"] <= prev_candle["high"]:
        return False

    sweep = curr_candle["high"] - prev_candle["high"]
    return sweep <= max_sweep


# ==========================================
# EMA CONTEXT LOGIC
# ------------------------------------------
# Two valid contexts:
#
# 1) FAR FROM 20 EMA -> moving back toward 20 EMA
#    target = 20 EMA
#
# 2) NEAR 20 EMA -> moving toward 200 EMA
#    target = 200 EMA
# ==========================================

def classify_ema_context(
    curr_candle: pd.Series,
    near_20_distance: float,
) -> Optional[dict]:
    """
    Classify the signal into one of your two EMA contexts.

    Returns:
    - None if no valid context
    - dict with:
        {
            "direction": "LONG" / "SHORT",
            "ema_context": "far_from_20_to_20" or "near_20_to_200",
            "target_type": "to_20ema" or "to_200ema",
            "target_price": ...
        }

    Logic:
    LONG:
    - If price is below 20 and far enough away -> target 20
    - If price is near 20 and 200 is above -> target 200

    SHORT:
    - If price is above 20 and far enough away -> target 20
    - If price is near 20 and 200 is below -> target 200
    """
    close = float(curr_candle["close"])
    ema20 = float(curr_candle["ema20"])
    ema200 = float(curr_candle["ema200"])

    distance_to_20 = abs(close - ema20)

    # LONG side
    if close < ema20:
        # Far below 20 -> moving back up to 20
        if distance_to_20 > near_20_distance:
            return {
                "direction": "LONG",
                "ema_context": "far_from_20_to_20",
                "target_type": "to_20ema",
                "target_price": ema20,
            }

        # Near 20 -> continue toward 200 if 200 is above
        if distance_to_20 <= near_20_distance and ema200 > close:
            return {
                "direction": "LONG",
                "ema_context": "near_20_to_200",
                "target_type": "to_200ema",
                "target_price": ema200,
            }

    # SHORT side
    if close > ema20:
        # Far above 20 -> moving back down to 20
        if distance_to_20 > near_20_distance:
            return {
                "direction": "SHORT",
                "ema_context": "far_from_20_to_20",
                "target_type": "to_20ema",
                "target_price": ema20,
            }

        # Near 20 -> continue toward 200 if 200 is below
        if distance_to_20 <= near_20_distance and ema200 < close:
            return {
                "direction": "SHORT",
                "ema_context": "near_20_to_200",
                "target_type": "to_200ema",
                "target_price": ema200,
            }

    return None


# ==========================================
# CORE STRATEGY
# ------------------------------------------
# Uses the LAST TWO CLOSED CANDLES:
# - prev = df.iloc[-2]
# - curr = df.iloc[-1]
#
# IMPORTANT:
# Make sure the DataFrame passed in only contains CLOSED candles
# or that the last row is the most recently CLOSED candle.
# ==========================================

def get_warden_wm_signal(
    df: pd.DataFrame,
    timeframe: str,
    stop_buffer: float,
    max_sweep: float,
    max_candle_size: float,
    near_20_distance: float,
    min_rr: float,
    body_ratio_threshold: float,
    min_bull_close_position: float,
    max_bear_close_position: float,
    full_body_min_ratio: float,
    sr_lookback: int,
    sr_tolerance: float,
) -> Optional[dict]:
    """
    Core signal function for Warden WM.

    Returns:
    - None if no valid signal
    - dict with trade setup if valid
    """
    validate_dataframe(df)

    # Need enough data for EMA200 + lookback + 2 candles
    min_bars = max(220, sr_lookback + 5)
    if len(df) < min_bars:
        return None

    # Add EMA columns
    work_df = add_emas(df)

    # Use last two CLOSED candles
    prev_candle = work_df.iloc[-2]
    curr_candle = work_df.iloc[-1]

    # Reject bad / zero-range candles
    curr_range = candle_range(curr_candle)
    if curr_range <= 0:
        return None

    # Reject oversized signal candles
    if curr_range > max_candle_size:
        return None

    # Require full-bodied signal candle
    curr_body_ratio = candle_body_ratio(curr_candle)
    if curr_body_ratio < full_body_min_ratio:
        return None

    # EMA context must be valid
    ema_context = classify_ema_context(curr_candle, near_20_distance)
    if ema_context is None:
        return None

    # Calculate recent support / resistance
    # Signal candle is at index len(work_df)-1
    signal_index = len(work_df) - 1
    recent_resistance = get_recent_resistance(work_df, signal_index, sr_lookback)
    recent_support = get_recent_support(work_df, signal_index, sr_lookback)

    # Signal candle close position
    close_pos = close_position_in_range(curr_candle)

    # --------------------------------------
    # LONG SETUP
    # --------------------------------------
    if ema_context["direction"] == "LONG":
        # Must be bullish engulfing / near-engulfing
        if not is_bullish_engulfing(prev_candle, curr_candle, body_ratio_threshold):
            return None

        # Anti stop-hunt: slight sweep below previous low only
        if not bullish_small_sweep(prev_candle, curr_candle, max_sweep):
            return None

        # Strong close near high
        if close_pos < min_bull_close_position:
            return None

        # Prefer near support / prior resistance zone flip
        # For bullish reversal we use recent support OR allow close near broken resistance
        near_support = is_near_level(curr_candle["low"], recent_support, sr_tolerance)
        near_resistance_flip = is_near_level(curr_candle["close"], recent_resistance, sr_tolerance)

        if not (near_support or near_resistance_flip):
            return None

        # Entry at close of engulfing candle
        entry_price = float(curr_candle["close"])

        # Stop a bit below low
        stop_price = float(curr_candle["low"] - stop_buffer)

        # Target from EMA context
        target_price = float(ema_context["target_price"])

        # Sanity checks
        if stop_price >= entry_price:
            return None

        if target_price <= entry_price:
            return None

        risk_price = entry_price - stop_price
        reward_price = target_price - entry_price

        if risk_price <= 0:
            return None

        rr = reward_price / risk_price

        if rr < min_rr:
            return None

        return {
            "strategy_name": "WardenWM",
            "timeframe": timeframe,
            "direction": "LONG",
            "signal_type": "bullish_engulf",
            "entry_price": round(entry_price, 10),
            "stop_price": round(stop_price, 10),
            "target_price": round(target_price, 10),
            "target_type": ema_context["target_type"],
            "ema_context": ema_context["ema_context"],
            "risk_price": round(risk_price, 10),
            "reward_price": round(reward_price, 10),
            "rr": round(rr, 4),
            "signal_candle_range": round(curr_range, 10),
            "signal_candle_body": round(candle_body(curr_candle), 10),
            "signal_body_ratio": round(curr_body_ratio, 4),
            "close_position": round(close_pos, 4),
            "sweep_distance": round(float(prev_candle["low"] - curr_candle["low"]), 10),
            "ema20": round(float(curr_candle["ema20"]), 10),
            "ema200": round(float(curr_candle["ema200"]), 10),
            "recent_support": round(float(recent_support), 10) if recent_support is not None else None,
            "recent_resistance": round(float(recent_resistance), 10) if recent_resistance is not None else None,
            "timestamp": str(work_df.index[-1]) if work_df.index is not None else None,
        }

    # --------------------------------------
    # SHORT SETUP
    # --------------------------------------
    if ema_context["direction"] == "SHORT":
        # Must be bearish engulfing / near-engulfing
        if not is_bearish_engulfing(prev_candle, curr_candle, body_ratio_threshold):
            return None

        # Anti stop-hunt: slight sweep above previous high only
        if not bearish_small_sweep(prev_candle, curr_candle, max_sweep):
            return None

        # Strong close near low
        if close_pos > max_bear_close_position:
            return None

        # Prefer near resistance / prior support zone flip
        near_resistance = is_near_level(curr_candle["high"], recent_resistance, sr_tolerance)
        near_support_flip = is_near_level(curr_candle["close"], recent_support, sr_tolerance)

        if not (near_resistance or near_support_flip):
            return None

        # Entry at close of engulfing candle
        entry_price = float(curr_candle["close"])

        # Stop a bit above high
        stop_price = float(curr_candle["high"] + stop_buffer)

        # Target from EMA context
        target_price = float(ema_context["target_price"])

        # Sanity checks
        if stop_price <= entry_price:
            return None

        if target_price >= entry_price:
            return None

        risk_price = stop_price - entry_price
        reward_price = entry_price - target_price

        if risk_price <= 0:
            return None

        rr = reward_price / risk_price

        if rr < min_rr:
            return None

        return {
            "strategy_name": "WardenWM",
            "timeframe": timeframe,
            "direction": "SHORT",
            "signal_type": "bearish_engulf",
            "entry_price": round(entry_price, 10),
            "stop_price": round(stop_price, 10),
            "target_price": round(target_price, 10),
            "target_type": ema_context["target_type"],
            "ema_context": ema_context["ema_context"],
            "risk_price": round(risk_price, 10),
            "reward_price": round(reward_price, 10),
            "rr": round(rr, 4),
            "signal_candle_range": round(curr_range, 10),
            "signal_candle_body": round(candle_body(curr_candle), 10),
            "signal_body_ratio": round(curr_body_ratio, 4),
            "close_position": round(close_pos, 4),
            "sweep_distance": round(float(curr_candle["high"] - prev_candle["high"]), 10),
            "ema20": round(float(curr_candle["ema20"]), 10),
            "ema200": round(float(curr_candle["ema200"]), 10),
            "recent_support": round(float(recent_support), 10) if recent_support is not None else None,
            "recent_resistance": round(float(recent_resistance), 10) if recent_resistance is not None else None,
            "timestamp": str(work_df.index[-1]) if work_df.index is not None else None,
        }

    return None


# ==========================================
# TIMEFRAME WRAPPER
# ------------------------------------------
# Use the correct settings automatically
# for:
# - 15m
# - 30m
# - 60m
# ==========================================

def get_warden_wm_signal_by_timeframe(
    df: pd.DataFrame,
    timeframe: str,
) -> Optional[dict]:
    """
    Run WardenWM using preconfigured timeframe settings.
    """
    settings = get_warden_wm_settings(timeframe)

    return get_warden_wm_signal(
        df=df,
        timeframe=timeframe,
        stop_buffer=settings["stop_buffer"],
        max_sweep=settings["max_sweep"],
        max_candle_size=settings["max_candle_size"],
        near_20_distance=settings["near_20_distance"],
        min_rr=settings["min_rr"],
        body_ratio_threshold=settings["body_ratio_threshold"],
        min_bull_close_position=settings["min_bull_close_position"],
        max_bear_close_position=settings["max_bear_close_position"],
        full_body_min_ratio=settings["full_body_min_ratio"],
        sr_lookback=settings["sr_lookback"],
        sr_tolerance=settings["sr_tolerance"],
    )


# ==========================================
# SINGLE SYMBOL SCAN
# ------------------------------------------
# Your exact rule:
# - only one trade per symbol
# - first valid timeframe wins
# ==========================================

def get_first_warden_wm_signal_for_symbol(
    symbol: str,
    timeframe_data: Dict[str, pd.DataFrame],
    has_open_trade: bool = False,
    timeframe_order=("15m", "30m", "60m"),
) -> Optional[dict]:
    """
    Find the first valid signal for a symbol.

    Args:
    - symbol: e.g. "EURUSD"
    - timeframe_data:
        {
            "15m": df_15m,
            "30m": df_30m,
            "60m": df_60m,
        }
    - has_open_trade:
        If True, skip symbol completely
    - timeframe_order:
        Order to scan if running in a batch loop

    Returns:
    - None if no valid signal or symbol already in trade
    - dict if signal found
    """
    if has_open_trade:
        return None

    for timeframe in timeframe_order:
        if timeframe not in timeframe_data:
            continue

        df = timeframe_data[timeframe]
        signal = get_warden_wm_signal_by_timeframe(df, timeframe)

        if signal is not None:
            signal["symbol"] = symbol
            return signal

    return None


# ==========================================
# MULTI-SYMBOL SCANNER
# ------------------------------------------
# Scans many symbols and returns the first
# valid signal per symbol (if any).
# ==========================================

def scan_warden_wm_multi_symbol(
    market_data: Dict[str, Dict[str, pd.DataFrame]],
    open_trade_symbols: Optional[List[str]] = None,
    timeframe_order=("15m", "30m", "60m"),
) -> List[dict]:
    """
    Scan multiple symbols.

    Args:
    - market_data:
        {
            "EURUSD": {
                "15m": df_15m,
                "30m": df_30m,
                "60m": df_60m,
            },
            "GBPUSD": {
                "15m": df_15m,
                "30m": df_30m,
                "60m": df_60m,
            },
            ...
        }

    - open_trade_symbols:
        List of symbols currently in a trade

    - timeframe_order:
        Scan order for each symbol

    Returns:
    - list of valid signal dicts
      (max 1 per symbol)
    """
    if open_trade_symbols is None:
        open_trade_symbols = []

    results = []

    for symbol, timeframe_data in market_data.items():
        has_open_trade = symbol in open_trade_symbols

        signal = get_first_warden_wm_signal_for_symbol(
            symbol=symbol,
            timeframe_data=timeframe_data,
            has_open_trade=has_open_trade,
            timeframe_order=timeframe_order,
        )

        if signal is not None:
            results.append(signal)

    return results


# ==========================================
# OPTIONAL: SIMPLE SIGNAL SUMMARY
# ------------------------------------------
# Handy for quick console logging
# ==========================================

def format_signal_summary(signal: dict) -> str:
    """
    Return a clean one-line summary for logs / console output.
    """
    return (
        f"[{signal.get('strategy_name')}] "
        f"{signal.get('symbol', 'UNKNOWN')} "
        f"{signal.get('timeframe')} "
        f"{signal.get('direction')} "
        f"{signal.get('signal_type')} | "
        f"Entry={signal.get('entry_price')} "
        f"Stop={signal.get('stop_price')} "
        f"Target={signal.get('target_price')} "
        f"RR={signal.get('rr')} "
        f"Context={signal.get('ema_context')}"
    )


# ==========================================
# EXAMPLE USAGE (SAFE TO REMOVE)
# ------------------------------------------
# This block only runs if you execute the file directly.
# It will NOT run when you import the file into your system.
# ==========================================

if __name__ == "__main__":
    # Example only:
    # Replace these with your real DataFrames from your candle engine.

    # Create a dummy DataFrame for demonstration
    rows = 250
    np.random.seed(42)

    prices = np.cumsum(np.random.randn(rows) * 0.0005) + 1.2500

    demo_df = pd.DataFrame({
        "open": prices,
        "high": prices + np.random.rand(rows) * 0.0008,
        "low": prices - np.random.rand(rows) * 0.0008,
        "close": prices + (np.random.randn(rows) * 0.0003),
    })

    # Make sure highs/lows are valid
    demo_df["high"] = demo_df[["open", "close", "high"]].max(axis=1)
    demo_df["low"] = demo_df[["open", "close", "low"]].min(axis=1)

    # Single timeframe test
    signal_15m = get_warden_wm_signal_by_timeframe(demo_df, "15m")

    if signal_15m:
        signal_15m["symbol"] = "DEMO"
        print("Single timeframe signal:")
        print(format_signal_summary(signal_15m))
    else:
        print("No 15m signal found.")

    # Single symbol multi-timeframe test
    symbol_data = {
        "15m": demo_df.copy(),
        "30m": demo_df.copy(),
        "60m": demo_df.copy(),
    }

    first_signal = get_first_warden_wm_signal_for_symbol(
        symbol="DEMO",
        timeframe_data=symbol_data,
        has_open_trade=False,
        timeframe_order=("15m", "30m", "60m"),
    )

    if first_signal:
        print("First valid symbol signal:")
        print(format_signal_summary(first_signal))
    else:
        print("No multi-timeframe signal found.")

    # Multi-symbol scan example
    market_data = {
        "EURUSD": {
            "15m": demo_df.copy(),
            "30m": demo_df.copy(),
            "60m": demo_df.copy(),
        },
        "GBPUSD": {
            "15m": demo_df.copy(),
            "30m": demo_df.copy(),
            "60m": demo_df.copy(),
        },
    }

    signals = scan_warden_wm_multi_symbol(
        market_data=market_data,
        open_trade_symbols=[],
        timeframe_order=("15m", "30m", "60m"),
    )

    if signals:
        print("\nMulti-symbol scan results:")
        for s in signals:
            print(format_signal_summary(s))
    else:
        print("\nNo multi-symbol signals found.")