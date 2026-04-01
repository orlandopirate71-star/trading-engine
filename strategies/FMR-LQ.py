# ==========================================
# FMR-LQ (Fractal Magnet Reversal - Liquidity Qualified)
# PRICE-NATIVE VERSION
# ------------------------------------------
# This version uses RAW PRICE VALUES only.
#
# You said your dashboard already handles:
# - pips
# - units
# - sizing
# - instrument-specific formatting
#
# So this strategy only returns:
# - entry price
# - stop price
# - target price
# - risk/reward in raw price
# - metadata for your execution layer
# ==========================================

import pandas as pd


# ==========================================
# BASIC EMA HELPERS
# ==========================================

def add_ema_columns(df, fast_period=20, slow_period=200):
    """
    Add EMA columns to a copy of the DataFrame.

    Required columns in df:
    - close

    Returns:
    - df copy with:
        ema_20
        ema_200
    """
    out = df.copy()

    # Exponential moving averages
    out["ema_20"] = out["close"].ewm(span=fast_period, adjust=False).mean()
    out["ema_200"] = out["close"].ewm(span=slow_period, adjust=False).mean()

    return out


# ==========================================
# CANDLE SHAPE HELPERS
# ==========================================

def candle_range(row):
    """
    Full candle range from high to low.
    """
    return row["high"] - row["low"]


def candle_body_size(row):
    """
    Absolute body size of the candle.
    """
    return abs(row["close"] - row["open"])


def get_close_position_in_candle(row):
    """
    Return where the close sits within the candle range.

    0.0 = close at low
    1.0 = close at high

    Useful for:
    - bullish close near high
    - bearish close near low
    """
    rng = candle_range(row)

    # Avoid divide-by-zero on flat candles
    if rng == 0:
        return 0.5

    return (row["close"] - row["low"]) / rng


def bullish_close_near_high(row, min_close_position=0.80):
    """
    Bullish candle should close near the high.

    Example:
    - 0.80 means close is in the top 20% of the candle range
    """
    return get_close_position_in_candle(row) >= min_close_position


def bearish_close_near_low(row, max_close_position=0.20):
    """
    Bearish candle should close near the low.

    Example:
    - 0.20 means close is in the bottom 20% of the candle range
    """
    return get_close_position_in_candle(row) <= max_close_position


# ==========================================
# ENGULFING / TAKEOVER DETECTION
# ==========================================

def is_bullish_engulf(curr, prev, body_ratio_threshold=0.90):
    """
    Detect a bullish engulfing / bullish takeover.

    Your version:
    - Previous candle should be bearish
    - Current candle should be bullish
    - Current body should be at least similar in size
      to the previous body (default 90%)
    - Current close should be above previous open
      (strong takeover)
    - Current open should be at or below previous close
      (body overlap / engulf logic)

    Returns:
    - True / False
    """
    prev_bearish = prev["close"] < prev["open"]
    curr_bullish = curr["close"] > curr["open"]

    prev_body = candle_body_size(prev)
    curr_body = candle_body_size(curr)

    # Avoid weird edge cases
    if prev_body == 0:
        return False

    body_ok = curr_body >= (prev_body * body_ratio_threshold)

    # Strong body takeover logic
    close_takes_prev_open = curr["close"] > prev["open"]
    open_near_prev_close = curr["open"] <= prev["close"]

    return (
        prev_bearish
        and curr_bullish
        and body_ok
        and close_takes_prev_open
        and open_near_prev_close
    )


def is_bearish_engulf(curr, prev, body_ratio_threshold=0.90):
    """
    Detect a bearish engulfing / bearish takeover.

    Your version:
    - Previous candle should be bullish
    - Current candle should be bearish
    - Current body should be at least similar in size
      to the previous body (default 90%)
    - Current close should be below previous open
      (strong takeover)
    - Current open should be at or above previous close
      (body overlap / engulf logic)

    Returns:
    - True / False
    """
    prev_bullish = prev["close"] > prev["open"]
    curr_bearish = curr["close"] < curr["open"]

    prev_body = candle_body_size(prev)
    curr_body = candle_body_size(curr)

    # Avoid weird edge cases
    if prev_body == 0:
        return False

    body_ok = curr_body >= (prev_body * body_ratio_threshold)

    # Strong body takeover logic
    close_takes_prev_open = curr["close"] < prev["open"]
    open_near_prev_close = curr["open"] >= prev["close"]

    return (
        prev_bullish
        and curr_bearish
        and body_ok
        and close_takes_prev_open
        and open_near_prev_close
    )


# ==========================================
# LIQUIDITY / STOP-HUNT FILTERS
# ==========================================

def bullish_sweep_is_controlled(curr, prev, max_sweep):
    """
    Bullish setup:
    - Current candle may dip below previous low
    - But only by a SMALL amount

    Why:
    - Avoid huge stop-hunt candles
    - Avoid oversized stop losses
    - Avoid trap candles

    Args:
    - max_sweep: maximum allowed price sweep below previous low

    Returns:
    - True if acceptable
    """
    sweep_distance = prev["low"] - curr["low"]

    # If <= 0, current candle did NOT sweep below previous low
    if sweep_distance <= 0:
        return True

    return sweep_distance <= max_sweep


def bearish_sweep_is_controlled(curr, prev, max_sweep):
    """
    Bearish setup:
    - Current candle may spike above previous high
    - But only by a SMALL amount

    Args:
    - max_sweep: maximum allowed price sweep above previous high

    Returns:
    - True if acceptable
    """
    sweep_distance = curr["high"] - prev["high"]

    # If <= 0, current candle did NOT sweep above previous high
    if sweep_distance <= 0:
        return True

    return sweep_distance <= max_sweep


def candle_not_too_large(row, max_candle_size):
    """
    Reject oversized signal candles.

    Why:
    - Often bad RR
    - Often news spikes
    - Often exhaustion candles
    """
    return candle_range(row) <= max_candle_size


# ==========================================
# EMA CONTEXT / TARGET LOGIC
# ==========================================

def get_ema_context(curr, near_20_distance):
    """
    Determine whether price is:
    - near the 20 EMA
    - far from the 20 EMA

    Your rule:
    - If price starts FAR from 20 EMA -> target the 20 EMA
    - If price starts ON / NEAR the 20 EMA -> target the 200 EMA

    We use the signal candle close as the reference price.

    Returns:
    - "near_20" or "far_from_20"
    """
    distance_to_20 = abs(curr["close"] - curr["ema_20"])

    if distance_to_20 <= near_20_distance:
        return "near_20"

    return "far_from_20"


def get_target_from_context(curr, direction, near_20_distance):
    """
    Build target logic based on your MA magnet rules.

    Rules:
    - If signal is FAR from 20 EMA -> TP = 20 EMA
    - If signal is ON / NEAR 20 EMA -> TP = 200 EMA

    Note:
    - We do NOT force EMA directional alignment here.
      You can add that later if needed.

    Returns:
    - (target_price, target_type)
    """
    context = get_ema_context(curr, near_20_distance)

    if context == "far_from_20":
        return curr["ema_20"], "to_20ema"

    return curr["ema_200"], "to_200ema"


# ==========================================
# RISK / REWARD HELPERS
# ==========================================

def calculate_long_rr(entry, stop, target):
    """
    Calculate risk/reward for a LONG trade.

    Returns:
    - (risk_price, reward_price, rr)
    """
    risk = entry - stop
    reward = target - entry

    # Invalid or broken trade geometry
    if risk <= 0:
        return None, None, None

    rr = reward / risk
    return risk, reward, rr


def calculate_short_rr(entry, stop, target):
    """
    Calculate risk/reward for a SHORT trade.

    Returns:
    - (risk_price, reward_price, rr)
    """
    risk = stop - entry
    reward = entry - target

    # Invalid or broken trade geometry
    if risk <= 0:
        return None, None, None

    rr = reward / risk
    return risk, reward, rr


# ==========================================
# MAIN SIGNAL FUNCTION
# ==========================================

def get_fmr_lq_signal(
    df,
    timeframe="15m",
    stop_buffer=0.0003,
    max_sweep=0.0005,
    max_candle_size=0.0020,
    near_20_distance=0.0005,
    min_rr=1.0,
    body_ratio_threshold=0.90,
    min_bull_close_position=0.80,
    max_bear_close_position=0.20,
):
    """
    Main plug-and-play FMR-LQ signal function.

    INPUT:
    - df must contain at least:
        open, high, low, close

    ASSUMPTION:
    - The latest row in df is the latest CLOSED candle
    - Your system handles the live / incomplete candle logic already

    RULES INCLUDED:
    - Bullish engulfing / takeover
    - Bearish engulfing / takeover
    - Strong close filter
    - Anti-stop-hunt sweep filter
    - Max candle size filter
    - 20 EMA / 200 EMA context
    - Target = 20 EMA or 200 EMA
    - Entry = close
    - Stop = beyond signal candle extreme
    - Minimum RR filter

    RETURNS:
    - None if no valid trade
    - Otherwise a dict with full trade info
    """
    # Need enough candles for:
    # - previous candle
    # - current signal candle
    # - EMA calculations
    if df is None or len(df) < 210:
        return None

    # Add EMA columns
    data = add_ema_columns(df)

    # Current signal candle = latest CLOSED candle
    curr = data.iloc[-1]

    # Previous candle
    prev = data.iloc[-2]

    # ------------------------------------------
    # 1) CHECK BULLISH ENGULFING / TAKEOVER
    # ------------------------------------------
    bull_engulf = is_bullish_engulf(
        curr=curr,
        prev=prev,
        body_ratio_threshold=body_ratio_threshold
    )

    if bull_engulf:
        # Strong close near the high
        close_ok = bullish_close_near_high(
            curr,
            min_close_position=min_bull_close_position
        )

        # Only a small liquidity sweep below previous candle low
        sweep_ok = bullish_sweep_is_controlled(
            curr=curr,
            prev=prev,
            max_sweep=max_sweep
        )

        # Reject oversized signal candles
        size_ok = candle_not_too_large(
            row=curr,
            max_candle_size=max_candle_size
        )

        if close_ok and sweep_ok and size_ok:
            # Entry = signal candle close
            entry = curr["close"]

            # Stop = a little below signal candle low
            stop = curr["low"] - stop_buffer

            # Target based on your EMA magnet logic
            target, target_type = get_target_from_context(
                curr=curr,
                direction="LONG",
                near_20_distance=near_20_distance
            )

            # Calculate RR
            risk_price, reward_price, rr = calculate_long_rr(
                entry=entry,
                stop=stop,
                target=target
            )

            # Reject broken geometry or poor RR
            if rr is not None and rr >= min_rr and reward_price > 0:
                return {
                    "strategy_name": "FMR-LQ",
                    "timeframe": timeframe,
                    "direction": "LONG",
                    "signal_type": "bullish_engulf",
                    "entry_price": float(entry),
                    "stop_price": float(stop),
                    "target_price": float(target),
                    "target_type": target_type,
                    "risk_price": float(risk_price),
                    "reward_price": float(reward_price),
                    "rr": float(rr),
                    "ema_20": float(curr["ema_20"]),
                    "ema_200": float(curr["ema_200"]),
                    "ema_context": get_ema_context(curr, near_20_distance),
                    "close_position": float(get_close_position_in_candle(curr)),
                    "signal_candle_range": float(candle_range(curr)),
                    "signal_candle_body": float(candle_body_size(curr)),
                    "sweep_distance": float(max(0.0, prev["low"] - curr["low"])),
                    "signal_index": data.index[-1],
                }

    # ------------------------------------------
    # 2) CHECK BEARISH ENGULFING / TAKEOVER
    # ------------------------------------------
    bear_engulf = is_bearish_engulf(
        curr=curr,
        prev=prev,
        body_ratio_threshold=body_ratio_threshold
    )

    if bear_engulf:
        # Strong close near the low
        close_ok = bearish_close_near_low(
            curr,
            max_close_position=max_bear_close_position
        )

        # Only a small liquidity sweep above previous candle high
        sweep_ok = bearish_sweep_is_controlled(
            curr=curr,
            prev=prev,
            max_sweep=max_sweep
        )

        # Reject oversized signal candles
        size_ok = candle_not_too_large(
            row=curr,
            max_candle_size=max_candle_size
        )

        if close_ok and sweep_ok and size_ok:
            # Entry = signal candle close
            entry = curr["close"]

            # Stop = a little above signal candle high
            stop = curr["high"] + stop_buffer

            # Target based on your EMA magnet logic
            target, target_type = get_target_from_context(
                curr=curr,
                direction="SHORT",
                near_20_distance=near_20_distance
            )

            # Calculate RR
            risk_price, reward_price, rr = calculate_short_rr(
                entry=entry,
                stop=stop,
                target=target
            )

            # Reject broken geometry or poor RR
            if rr is not None and rr >= min_rr and reward_price > 0:
                return {
                    "strategy_name": "FMR-LQ",
                    "timeframe": timeframe,
                    "direction": "SHORT",
                    "signal_type": "bearish_engulf",
                    "entry_price": float(entry),
                    "stop_price": float(stop),
                    "target_price": float(target),
                    "target_type": target_type,
                    "risk_price": float(risk_price),
                    "reward_price": float(reward_price),
                    "rr": float(rr),
                    "ema_20": float(curr["ema_20"]),
                    "ema_200": float(curr["ema_200"]),
                    "ema_context": get_ema_context(curr, near_20_distance),
                    "close_position": float(get_close_position_in_candle(curr)),
                    "signal_candle_range": float(candle_range(curr)),
                    "signal_candle_body": float(candle_body_size(curr)),
                    "sweep_distance": float(max(0.0, curr["high"] - prev["high"])),
                    "signal_index": data.index[-1],
                }

    # No valid signal
    return None