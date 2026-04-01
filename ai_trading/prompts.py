"""
Prompt templates for AI Trade Validator and Position Monitor.
"""

# ============================================================================
# SYSTEM PROMPTS
# ============================================================================

SIGNAL_VALIDATOR_SYSTEM = """You are an expert trading analyst with deep knowledge of technical analysis, price action, and strategy execution. You validate trade signals before execution.

Your role:
1. Verify the signal aligns with the strategy's rules
2. Check market context for favorable conditions
3. Validate risk/reward ratios
4. Confirm entry timing

Output JSON only. No markdown, no explanation outside JSON."""


POSITION_MONITOR_SYSTEM = """You are an expert position manager monitoring live trades.

Your role:
1. Detect trend changes before they fully develop
2. Identify when to close trades (strong reversal signals)
3. Identify when to extend winning trades (strong momentum)
4. Determine optimal trailing stop levels
5. Monitor market conditions that could invalidate the trade

Output JSON only. No markdown, no explanation outside JSON."""


# Optimized system prompt for local LLM (qwen2.5:14b)
POSITION_MONITOR_SYSTEM_LOCAL = """You are a professional forex/crypto position manager. Analyze open positions and make clear decisions.

RULES:
- HOLD: Price moving with trend, no reversal signals
- CLOSE: Strong reversal pattern or invalidation
- EXTEND: Strong momentum in direction of trade
- TRAIL_STOP: Lock profits by moving SL to breakeven or better
- ADJUST_TP: TP needs adjustment based on new levels

Always output valid JSON. Be decisive."""


# Optimized prompt for local LLM - shorter, more structured
POSITION_MONITOR_PROMPT_LOCAL = """## POSITION
Symbol: {symbol} | Direction: {direction}
Entry: {entry} | Current: {current}
SL: {sl} | TP: {tp}
P&L: {pnl_pct:.2f}%

## MARKET
{market_context}

## RECENT PRICE ACTION
{candles_text}

## DECISION
Choose ONE action: HOLD, CLOSE, EXTEND, TRAIL_STOP, ADJUST_TP

Respond with JSON:
{{
  "action": "HOLD|CLOSE|EXTEND|TRAIL_STOP|ADJUST_TP",
  "confidence": 0.0-1.0,
  "reasoning": "brief technical reason",
  "urgency": "low|medium|high",
  "new_stop_loss": number_or_null,
  "new_take_profit": number_or_null,
  "close_percentage": 0.0-1.0
}}"""


def position_monitor_prompt_local(
    position_data: dict,
    market_context: str,
    recent_candles: list
) -> str:
    """
    Generate optimized prompt for local LLM (qwen2.5:14b) monitoring.
    Shorter, more structured format for smaller models.
    """
    symbol = position_data.get("symbol", "UNKNOWN")
    direction = position_data.get("direction", "UNKNOWN")
    entry = position_data.get("entry_price", 0)
    current = position_data.get("current_price", 0)
    sl = position_data.get("stop_loss", 0)
    tp = position_data.get("take_profit", 0)
    unrealized_pnl = position_data.get("unrealized_pnl", 0)
    
    # Calculate current profit/loss
    if entry > 0 and current > 0:
        if direction.upper() == "LONG":
            pnl_pct = ((current - entry) / entry) * 100
        else:
            pnl_pct = ((entry - current) / entry) * 100
    else:
        pnl_pct = 0
    
    # Format candles - simpler format for local LLM
    candles_text = ""
    if recent_candles:
        lines = []
        for c in recent_candles[:10]:  # Limit to 10 candles for local model
            time_str = c.get("time", c.get("timestamp", ""))[-8:] if c.get("time") else ""
            o = c.get("open", 0)
            h = c.get("high", 0)
            l = c.get("low", 0)
            c_val = c.get("close", 0)
            trend = "↑" if c_val > o else "↓" if c_val < o else "→"
            lines.append(f"{time_str} {trend} O:{o:.4f} H:{h:.4f} L:{l:.4f} C:{c_val:.4f}")
        candles_text = "\n".join(lines)
    else:
        candles_text = "No recent data"
    
    # Simplified market context
    market_summary = market_context[:500] if len(market_context) > 500 else market_context
    
    return POSITION_MONITOR_PROMPT_LOCAL.format(
        symbol=symbol,
        direction=direction.upper(),
        entry=entry,
        current=current,
        sl=sl,
        tp=tp,
        pnl_pct=pnl_pct,
        market_context=market_summary,
        candles_text=candles_text
    )

def signal_validation_prompt(
    strategy_name: str,
    strategy_code: str,
    strategy_context: str,
    signal_data: dict,
    market_context: str,
    candles_by_timeframe: dict = None,
    market_info: dict = None
) -> str:
    """
    Generate the prompt for validating a trade signal.

    Args:
        strategy_name: Name of the strategy generating the signal
        strategy_code: The strategy's Python code
        strategy_context: Brain context for the strategy
        signal_data: Dict with symbol, direction, entry_price, sl, tp, etc.
        market_context: Current market conditions
        candles_by_timeframe: Dict of {timeframe: [candles]} for multi-TF analysis
        market_info: Optional dict with 24h_high, 24h_low, daily_change, current_price

    Returns:
        Formatted prompt string
    """
    candles_by_timeframe = candles_by_timeframe or {}
    direction = signal_data.get("direction", "UNKNOWN")
    symbol = signal_data.get("symbol", "UNKNOWN")
    entry = signal_data.get("entry_price", 0)
    sl = signal_data.get("stop_loss", 0)
    tp = signal_data.get("take_profit", 0)
    confidence = signal_data.get("confidence", 0.5)
    reason = signal_data.get("reason", "")
    units = signal_data.get("units", 0)  # Position size

    # Calculate risk/reward
    risk_amount = 0
    if sl > 0 and tp > 0 and entry > 0:
        if direction.upper() == "LONG":
            risk = entry - sl
            reward = tp - entry
            risk_amount = risk * units if units > 0 else 0
        else:
            risk = sl - entry
            reward = entry - tp
            risk_amount = risk * units if units > 0 else 0
        rr_ratio = reward / risk if risk > 0 else 0
    else:
        rr_ratio = 0

    # 24h market info
    h24_info = ""
    if market_info:
        h24_info = f"""
## 24H MARKET INFO
- **24h High:** {market_info.get('h24_high', 'N/A')}
- **24h Low:** {market_info.get('h24_low', 'N/A')}
- **Daily Change:** {market_info.get('daily_change', 'N/A')}
- **Current Price:** {market_info.get('current_price', entry)}
"""

    # Format candles for each timeframe
    candles_text = ""
    for tf, candles in sorted(candles_by_timeframe.items()):
        if candles:
            candles_text += f"\n## {tf} CANDLES ({len(candles)} bars)\n"
            candles_text += _format_candles(candles)

    return f"""## SIGNAL TO VALIDATE

**Symbol:** {symbol}
**Direction:** {direction.upper()}
**Entry Price:** {entry}
**Stop Loss:** {sl}
**Take Profit:** {tp}
**Risk/Reward Ratio:** {rr_ratio:.2f}
**Strategy Confidence:** {confidence}
**Signal Reason:** {reason}
**Position Size (units):** {units}
**Estimated Risk ($):** ${risk_amount:.2f}

## STRATEGY: {strategy_name}

### Strategy Code
```python
{strategy_code}
```

### Brain Context
{strategy_context}

{h24_info}
## MARKET CONTEXT
{market_context}

{candles_text}

## VALIDATION CHECKLIST

Analyze and respond with:

1. **signal_valid**: boolean - Should this signal be executed?
2. **confidence**: float 0-1 - Your confidence level
3. **reasoning**: string - Brief explanation of your decision
4. **risk_score**: float 0-1 - Risk level (1 = high risk)
5. **market_alignment**: float 0-1 - How well market conditions align (1 = perfect)
6. **recommendations**: list of strings - Suggestions to improve the trade

Consider:
- Does the signal match strategy rules?
- Is the risk/reward favorable (>1.5 is good)?
- Are market conditions supportive?
- Is the entry timing good?
- Any conflicting signals?

Return JSON:
```json
{{
  "signal_valid": true/false,
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation",
  "risk_score": 0.0-1.0,
  "market_alignment": 0.0-1.0,
  "recommendations": ["suggestion1", "suggestion2"]
}}
```"""


def _format_candles(candles: list) -> str:
    """Format candles for prompt."""
    if not candles:
        return "No candle data available"

    lines = []
    for i, c in enumerate(candles[:20]):  # Limit to 20 candles
        time = c.get("time", c.get("timestamp", ""))
        o = c.get("open", 0)
        h = c.get("high", 0)
        l = c.get("low", 0)
        c_val = c.get("close", 0)
        v = c.get("volume", 0)

        # Determine if bullish or bearish
        if c_val > o:
            emoji = "🟢"
        elif c_val < o:
            emoji = "🔴"
        else:
            emoji = "⚪"

        lines.append(f"{emoji} {time}: O={o:.5f} H={h:.5f} L={l:.5f} C={c_val:.5f} V={v}")

    return "\n".join(lines)


# ============================================================================
# POSITION MONITOR PROMPT
# ============================================================================

def position_monitor_prompt(
    position_data: dict,
    market_context: str,
    recent_candles: list,
    open_trade_history: list
) -> str:
    """
    Generate prompt for monitoring an open position.

    Args:
        position_data: Current position state
        market_context: Brain context for current market
        recent_candles: Recent candles for analysis
        open_trade_history: Other open positions for correlation

    Returns:
        Formatted prompt string
    """
    symbol = position_data.get("symbol", "UNKNOWN")
    direction = position_data.get("direction", "UNKNOWN")
    entry = position_data.get("entry_price", 0)
    current = position_data.get("current_price", 0)
    sl = position_data.get("stop_loss", 0)
    tp = position_data.get("take_profit", 0)
    unrealized_pnl = position_data.get("unrealized_pnl", 0)
    quantity = position_data.get("quantity", 0)

    # Calculate current profit/loss
    if entry > 0 and current > 0:
        if direction.upper() == "LONG":
            pnl_pct = ((current - entry) / entry) * 100
        else:
            pnl_pct = ((entry - current) / entry) * 100
    else:
        pnl_pct = 0

    candles_text = _format_candles(recent_candles)

    # Format other open positions for correlation
    other_positions = []
    for pos in open_trade_history[:5]:
        if pos.get("symbol") != symbol:
            other_positions.append(
                f"- {pos.get('symbol')} {pos.get('direction')} {pos.get('unrealized_pnl', 0):.2f}"
            )
    other_pos_text = "\n".join(other_positions) if other_positions else "None"

    return f"""## POSITION TO MONITOR

**Symbol:** {symbol}
**Direction:** {direction.upper()}
**Entry Price:** {entry}
**Current Price:** {current}
**Stop Loss:** {sl}
**Take Profit:** {tp}
**Quantity:** {quantity}
**Unrealized P&L:** ${unrealized_pnl:.2f} ({pnl_pct:.2f}%)

## MARKET CONTEXT
{market_context}

## RECENT CANDLES (Latest First)
{candles_text}

## OTHER OPEN POSITIONS (For Correlation)
{other_pos_text}

## DECISION REQUIRED

Analyze the position and respond with ONE of these actions:

1. **HOLD** - Continue holding, conditions are favorable
2. **CLOSE** - Close the position now (strong reversal, trend change, or risk)
3. **EXTEND** - Add to position or let it run more (strong momentum)
4. **TRAIL_STOP** - Adjust stop loss to lock in profit (moving SL)
5. **ADJUST_TP** - Take profit needs adjustment

Response JSON:
```json
{{
  "action": "HOLD|CLOSE|EXTEND|TRAIL_STOP|ADJUST_TP",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation",
  "urgency": "low|medium|high",
  "new_stop_loss": number_or_null,
  "new_take_profit": number_or_null,
  "close_percentage": 0.0-1.0,
  "warnings": ["warning1", "warning2"]
}}
```

Consider:
- Is the trend still intact?
- Any reversal patterns forming?
- Is price approaching key levels?
- How correlated is this with other positions?
- Is momentum increasing or fading?
- News or events that could impact?"""


# ============================================================================
# BRAIN UPDATE PROMPT
# ============================================================================

def brain_update_prompt(
    action: str,
    trade_data: dict,
    ai_reasoning: str,
    outcome: str = "pending"
) -> str:
    """
    Generate memory content for Brain update after validation/monitoring.

    Returns:
        Formatted string to store in Brain
    """
    return f"""# AI Trade Analysis

## Action: {action}
## Trade: {trade_data.get('symbol', 'UNKNOWN')} {trade_data.get('direction', '').upper()}
## Outcome: {outcome}

### AI Reasoning
{ai_reasoning}

### Trade Details
- Entry: {trade_data.get('entry_price', 'N/A')}
- Exit: {trade_data.get('exit_price', 'N/A')}
- Stop Loss: {trade_data.get('stop_loss', 'N/A')}
- Take Profit: {trade_data.get('take_profit', 'N/A')}
- P&L: ${trade_data.get('pnl', 0):.2f}

### Timestamp
{trade_data.get('timestamp', 'N/A')}
"""
