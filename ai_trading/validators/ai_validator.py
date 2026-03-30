"""
AI Validator - Wrapper that integrates AI Signal Validator with trading engine.
Provides interface compatible with OpenClaw for seamless replacement.
"""
import sys
import os
from typing import Optional, Tuple

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from models import Trade, TradeSignal, TradeDirection, TradeStatus
from ai_trading.validators.signal_validator import SignalValidator, ValidationResult
from ai_trading.validators.position_monitor import PositionMonitor
from ai_trading.ai_client import get_ai_client, init_ai_client, Provider
from ai_trading.brain_client import get_brain_client


class AITradeValidator:
    """
    AI-powered trade validator that replaces OpenClaw.

    Interface matches OpenClaw for seamless trading engine integration:
    - validate_signal(signal, market_context) -> (should_execute, trade)
    - set_auto_trade(enabled)
    - set_require_approval(required)
    """

    def __init__(
        self,
        min_confidence: float = 0.6,
        max_risk_score: float = 0.7,
        auto_trade: bool = True,
        require_approval: bool = False,
        ollama_model: str = "gpt-oss:120b-cloud"
    ):
        """
        Initialize AI validator.

        Args:
            min_confidence: Minimum confidence to approve signal (0-1)
            max_risk_score: Maximum risk score to allow (0-1)
            auto_trade: If True, approved signals auto-execute
            require_approval: If True, approved signals need manual confirmation
            ollama_model: Model to use for Ollama
        """
        # Initialize AI client with working local model
        init_ai_client(
            primary=Provider.OLLAMA,
            ollama_model=ollama_model,
            ollama_base="http://localhost:11434"
        )

        self.validator = SignalValidator(
            min_confidence=min_confidence,
            max_risk_score=max_risk_score
        )

        self.auto_trade = auto_trade
        self.require_approval = require_approval
        self._enabled = True

        print(f"[AI Validator] Initialized with model {ollama_model}")
        print(f"[AI Validator] min_confidence={min_confidence}, max_risk={max_risk_score}")
        print(f"[AI Validator] auto_trade={auto_trade}, require_approval={require_approval}")

    def validate_signal(
        self,
        signal: TradeSignal,
        market_context: dict = None
    ) -> Tuple[bool, Trade]:
        """
        Validate a trade signal using AI.

        Args:
            signal: TradeSignal to validate
            market_context: Optional market context dict

        Returns:
            Tuple of (should_execute, trade)
            - should_execute: True if signal is approved and should auto-execute
            - trade: Trade object with validation results
        """
        if not self._enabled:
            print(f"[AI Validator] Validator disabled - rejecting signal")
            return False, self._create_trade_from_signal(signal, approved=False)

        # Build signal data dict for AI validator
        signal_data = {
            "symbol": signal.symbol,
            "direction": signal.direction.value if hasattr(signal.direction, 'value') else str(signal.direction),
            "entry_price": signal.entry_price,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "confidence": signal.confidence,
            "reason": signal.reason,
            "strategy_name": signal.strategy_name
        }

        # Get strategy source code
        from strategy_loader import get_strategy_loader
        loader = get_strategy_loader()
        strategy_source = loader.get_strategy_source(signal.strategy_name) or ""

        # Get recent candles from database for AI analysis (multiple timeframes)
        try:
            from candle_store import get_candle_store
            candle_store = get_candle_store()
            candles_by_timeframe = {}
            for tf in ["M15", "M30", "H1", "H4"]:
                candles_by_timeframe[tf] = candle_store.get_recent_candles(signal.symbol, tf, count=20)
            # Fallback to M5 if needed
            if not candles_by_timeframe.get("M15"):
                candles_by_timeframe["M5"] = candle_store.get_recent_candles(signal.symbol, "M5", count=20)
        except Exception as e:
            print(f"[AI Validator] Failed to get candles: {e}")
            candles_by_timeframe = {}

        # Get 24h market info from OANDA
        market_info = None
        try:
            import json
            from pathlib import Path
            from oanda_broker import OandaBroker
            
            # Load OANDA credentials from feed_config.json
            config_path = Path(__file__).parent.parent.parent / "feed_config.json"
            with open(config_path) as f:
                config = json.load(f)
            
            # Find OANDA feed config
            oanda_config = None
            for feed in config.get("feeds", []):
                if feed.get("type") == "oanda" and feed.get("enabled"):
                    oanda_config = feed
                    break
            
            if oanda_config:
                broker = OandaBroker(
                    oanda_config["account_id"],
                    oanda_config["api_token"],
                    practice=oanda_config.get("practice", True)
                )
                candles = broker.get_instrument_candles(signal.symbol, "D1", count=2)
                if candles and len(candles) >= 2:
                    current_candle = candles[0]  # Most recent
                    prev_candle = candles[1]    # Previous day
                    prev_close = prev_candle.get("close", 0)
                    current_close = current_candle.get("close", 0)
                    h24_high = current_candle.get("high", 0)
                    h24_low = current_candle.get("low", 0)
                    daily_change = ((current_close - prev_close) / prev_close * 100) if prev_close > 0 else 0
                    market_info = {
                        "h24_high": h24_high,
                        "h24_low": h24_low,
                        "daily_change": f"{daily_change:+.2f}%",
                        "current_price": signal.entry_price
                    }
        except Exception as e:
            print(f"[AI Validator] Failed to get market info: {e}")

        # Run AI validation
        try:
            result = self.validator.validate(
                signal_data=signal_data,
                strategy_name=signal.strategy_name,
                strategy_code=strategy_source,
                candles_by_timeframe=candles_by_timeframe,
                market_context=market_context.get("current_price") if market_context else None,
                market_info=market_info
            )

            print(f"[AI Validator] {signal.symbol} {signal.direction}: approved={result.approved}, confidence={result.confidence:.2f}, risk={result.risk_score:.2f}")
            print(f"[AI Validator] Reasoning: {result.reasoning[:200]}...")

            # Log to Redis for dashboard
            try:
                from connections import redis_client
                import json
                event = {
                    "type": "signal_validation",
                    "symbol": signal.symbol,
                    "direction": str(signal.direction),
                    "approved": result.approved,
                    "confidence": result.confidence,
                    "risk_score": result.risk_score,
                    "reasoning": result.reasoning[:300],
                    "provider": result.provider,
                    "latency_ms": result.latency_ms
                }
                redis_client.lpush("ai_activity_log", json.dumps(event))
                redis_client.ltrim("ai_activity_log", 0, 499)
            except Exception as log_err:
                pass  # Don't fail validation for logging errors

        except Exception as e:
            print(f"[AI Validator] Validation error: {e}")
            result = ValidationResult(
                approved=False,
                confidence=0.0,
                reasoning=f"Error: {str(e)}",
                risk_score=1.0,
                market_alignment=0.0,
                recommendations=[],
                latency_ms=0,
                provider="error"
            )

        # Create trade from signal
        trade = self._create_trade_from_signal(signal, approved=result.approved)

        # Add AI analysis to trade
        trade.openclaw_approved = result.approved
        trade.openclaw_confidence = result.confidence
        trade.openclaw_analysis = result.reasoning

        # Determine if should execute
        if not result.approved:
            should_execute = False
        elif self.require_approval:
            should_execute = False  # Needs manual approval
        elif not self.auto_trade:
            should_execute = False  # Auto trade disabled
        else:
            should_execute = True

        return should_execute, trade

    def _create_trade_from_signal(self, signal: TradeSignal, approved: bool) -> Trade:
        """Create a Trade object from a TradeSignal."""
        return Trade(
            id=0,  # Will be assigned by database
            signal_id=signal.id,
            strategy_name=signal.strategy_name,
            symbol=signal.symbol,
            direction=signal.direction,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            quantity=0,  # Set by executor based on symbol units
            leverage=1,
            status=TradeStatus.PENDING if not approved else TradeStatus.APPROVED,
            entry_time=None,
            exit_time=None,
            pnl=0,
            pnl_percent=0,
            fees=0,
            openclaw_approved=approved,
            openclaw_analysis="",
            openclaw_confidence=0,
            signal_time=signal.timestamp,
            approved_time=None,
            entry_screenshot=None,
            exit_screenshot=None,
            metadata={},
            trailing_stop_trigger=None,
            trailing_stop_lock=None,
            trailing_stop_activated=False
        )

    def set_auto_trade(self, enabled: bool):
        """Enable/disable auto trading."""
        self.auto_trade = enabled
        print(f"[AI Validator] Auto trade {'enabled' if enabled else 'disabled'}")

    def set_require_approval(self, required: bool):
        """Enable/disable requiring approval for trades."""
        self.require_approval = required
        print(f"[AI Validator] Require approval {'enabled' if required else 'disabled'}")

    def set_enabled(self, enabled: bool):
        """Enable/disable the validator entirely."""
        self._enabled = enabled
        print(f"[AI Validator] Validator {'enabled' if enabled else 'disabled'}")


# Singleton instance
_validator = None


def get_ai_validator() -> AITradeValidator:
    """Get or create the AI validator singleton."""
    global _validator
    if _validator is None:
        _validator = AITradeValidator()
    return _validator


def init_ai_validator(
    min_confidence: float = 0.6,
    max_risk_score: float = 0.7,
    auto_trade: bool = True,
    require_approval: bool = False,
    ollama_model: str = "gpt-oss:120b-cloud"
) -> AITradeValidator:
    """Initialize the AI validator with settings."""
    global _validator
    _validator = AITradeValidator(
        min_confidence=min_confidence,
        max_risk_score=max_risk_score,
        auto_trade=auto_trade,
        require_approval=require_approval,
        ollama_model=ollama_model
    )
    return _validator
