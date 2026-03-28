"""
AI Signal Validator - Validates trade signals before execution.
Replaces OpenClaw as the AI-powered trade validation layer.
"""
import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, List

from ai_trading.ai_client import get_ai_client, AIClient, AIResponse
from ai_trading.brain_client import get_brain_client, BrainClient
from ai_trading.prompts import (
    SIGNAL_VALIDATOR_SYSTEM,
    signal_validation_prompt,
    brain_update_prompt
)


@dataclass
class ValidationResult:
    """Result of signal validation."""
    approved: bool
    confidence: float
    reasoning: str
    risk_score: float
    market_alignment: float
    recommendations: List[str]
    latency_ms: float
    provider: str

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "risk_score": self.risk_score,
            "market_alignment": self.market_alignment,
            "recommendations": self.recommendations,
            "latency_ms": self.latency_ms,
            "provider": self.provider
        }


class SignalValidator:
    """
    AI-powered signal validator that:
    1. Queries Brain for strategy context
    2. Analyzes signal against strategy rules
    3. Checks market conditions
    4. Validates risk/reward
    5. Returns approval/rejection with confidence
    """

    def __init__(
        self,
        ai_client: Optional[AIClient] = None,
        brain_client: Optional[BrainClient] = None,
        min_confidence: float = 0.6,
        max_risk_score: float = 0.7
    ):
        """
        Initialize the signal validator.

        Args:
            ai_client: AI client for LLM inference
            brain_client: Brain client for strategy context
            min_confidence: Minimum confidence to approve (0-1)
            max_risk_score: Maximum risk score to allow (0-1)
        """
        self.ai = ai_client or get_ai_client()
        self.brain = brain_client or get_brain_client()
        self.min_confidence = min_confidence
        self.max_risk_score = max_risk_score

    def validate(
        self,
        signal_data: dict,
        strategy_name: str,
        strategy_code: str,
        recent_candles: Optional[List[dict]] = None,
        market_context: Optional[str] = None,
        market_info: Optional[dict] = None
    ) -> ValidationResult:
        """
        Validate a trade signal.

        Args:
            signal_data: Dict with symbol, direction, entry_price, sl, tp, etc.
            strategy_name: Name of the strategy generating the signal
            strategy_code: Python code of the strategy
            recent_candles: Recent candle data for technical analysis
            market_context: Optional pre-fetched market context
            market_info: Optional dict with h24_high, h24_low, daily_change

        Returns:
            ValidationResult with approval decision
        """
        start_time = time.time()

        # Get strategy context from Brain
        strategy_context = self.brain.get_strategy_context(strategy_name)

        # Get market context if not provided
        if not market_context:
            symbol = signal_data.get("symbol", "")
            market_context = self.brain.get_market_context(symbol)

        # Build the prompt
        prompt = signal_validation_prompt(
            strategy_name=strategy_name,
            strategy_code=strategy_code,
            strategy_context=strategy_context,
            signal_data=signal_data,
            market_context=market_context,
            recent_candles=recent_candles or [],
            market_info=market_info
        )

        # Get AI response
        try:
            response = self.ai.generate(
                prompt=prompt,
                system=SIGNAL_VALIDATOR_SYSTEM,
                max_tokens=2048,
                temperature=0.3
            )

            # Parse JSON response
            result = self._parse_response(response)

            # Apply thresholds
            approved = (
                result.confidence >= self.min_confidence and
                result.risk_score <= self.max_risk_score and
                result.approved  # AI also said valid
            )

            result.approved = approved

            # Update Brain with validation
            self._update_brain(signal_data, result)

            return result

        except Exception as e:
            print(f"[SignalValidator] Error: {e}")
            # Fail safe: reject on error
            return ValidationResult(
                approved=False,
                confidence=0.0,
                reasoning=f"Validation error: {str(e)}",
                risk_score=1.0,
                market_alignment=0.0,
                recommendations=["System error - default reject"],
                latency_ms=time.time() - start_time,
                provider="error"
            )

    def _parse_response(self, response: AIResponse) -> ValidationResult:
        """Parse AI response into ValidationResult."""
        data = self.ai.extract_json(response)

        if data:
            return ValidationResult(
                approved=data.get("signal_valid", False),
                confidence=float(data.get("confidence", 0.5)),
                reasoning=str(data.get("reasoning", "")),
                risk_score=float(data.get("risk_score", 0.5)),
                market_alignment=float(data.get("market_alignment", 0.5)),
                recommendations=data.get("recommendations", []),
                latency_ms=response.latency_ms,
                provider=response.provider.value
            )

        # Fallback parsing if JSON extraction fails
        content = response.content.lower()

        # Simple keyword-based fallback
        if "signal_valid" in content or "approved" in content:
            approved = "true" in content and "false" not in content.split("true")[0].split("approved")[0][-50:]
        else:
            approved = "valid" in content and "invalid" not in content

        return ValidationResult(
            approved=approved,
            confidence=0.5,
            reasoning=response.content[:500],
            risk_score=0.5,
            market_alignment=0.5,
            recommendations=[],
            latency_ms=response.latency_ms,
            provider=response.provider.value
        )

    def _update_brain(self, signal_data: dict, result: ValidationResult):
        """Update Brain with validation result for learning."""
        try:
            prompt = brain_update_prompt(
                action="VALIDATE",
                trade_data=signal_data,
                ai_reasoning=result.reasoning,
                outcome="pending"
            )
            self.brain.add_memory(
                content=prompt,
                memory_type="signal_validation",
                metadata={
                    "symbol": signal_data.get("symbol"),
                    "strategy_name": signal_data.get("strategy_name"),
                    "direction": signal_data.get("direction"),
                    "approved": result.approved,
                    "confidence": result.confidence
                }
            )
        except Exception as e:
            print(f"[SignalValidator] Failed to update Brain: {e}")


# Singleton instance
_validator: Optional[SignalValidator] = None


def get_signal_validator() -> SignalValidator:
    """Get or create the signal validator singleton."""
    global _validator
    if _validator is None:
        _validator = SignalValidator()
    return _validator


def validate_signal(
    signal_data: dict,
    strategy_name: str,
    strategy_code: str,
    recent_candles: Optional[List[dict]] = None
) -> ValidationResult:
    """
    Convenience function to validate a signal.

    Usage:
        result = validate_signal(
            signal_data={
                "symbol": "EURUSD",
                "direction": "long",
                "entry_price": 1.0850,
                "stop_loss": 1.0800,
                "take_profit": 1.0950
            },
            strategy_name="BreakoutStrategy",
            strategy_code=open("strategies/breakout.py").read(),
            recent_candles=candles
        )

        if result.approved:
            execute_trade(...)
    """
    return get_signal_validator().validate(
        signal_data=signal_data,
        strategy_name=strategy_name,
        strategy_code=strategy_code,
        recent_candles=recent_candles
    )
