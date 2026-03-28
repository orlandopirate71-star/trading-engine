"""
AI Position Monitor - Monitors open positions and makes management decisions.
Handles trailing stops, position extensions, and early closures.
"""
import json
import time
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum

from ai_trading.ai_client import get_ai_client, AIClient, AIResponse
from ai_trading.brain_client import get_brain_client, BrainClient
from ai_trading.prompts import (
    POSITION_MONITOR_SYSTEM,
    position_monitor_prompt,
    brain_update_prompt
)


class PositionAction(Enum):
    HOLD = "HOLD"
    CLOSE = "CLOSE"
    EXTEND = "EXTEND"
    TRAIL_STOP = "TRAIL_STOP"
    ADJUST_TP = "ADJUST_TP"


@dataclass
class MonitorResult:
    """Result of position monitoring decision."""
    action: PositionAction
    confidence: float
    reasoning: str
    urgency: str  # low, medium, high
    new_stop_loss: Optional[float]
    new_take_profit: Optional[float]
    close_percentage: float  # 0.0-1.0, how much to close
    warnings: List[str]
    latency_ms: float
    provider: str

    def to_dict(self) -> dict:
        return {
            "action": self.action.value,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "urgency": self.urgency,
            "new_stop_loss": self.new_stop_loss,
            "new_take_profit": self.new_take_profit,
            "close_percentage": self.close_percentage,
            "warnings": self.warnings,
            "latency_ms": self.latency_ms,
            "provider": self.provider
        }


class PositionMonitor:
    """
    AI-powered position monitor that:
    1. Monitors open positions at configurable intervals
    2. Analyzes market conditions and trend changes
    3. Makes decisions: hold, close, extend, trail stop
    4. Updates Brain with analysis for learning
    """

    def __init__(
        self,
        ai_client: Optional[AIClient] = None,
        brain_client: Optional[BrainClient] = None,
        check_interval: float = 30.0,  # seconds between checks
        confidence_threshold: float = 0.7,  # min confidence for actions
        urgency_high_threshold: float = 0.85,  # confidence for high urgency actions
        enabled: bool = True
    ):
        """
        Initialize the position monitor.

        Args:
            ai_client: AI client for LLM inference
            brain_client: Brain client for market context
            check_interval: Seconds between position checks
            confidence_threshold: Min confidence for any action
            urgency_high_threshold: Confidence level for high urgency actions
            enabled: Whether monitoring is active
        """
        self.ai = ai_client or get_ai_client()
        self.brain = brain_client or get_brain_client()
        self.check_interval = check_interval
        self.confidence_threshold = confidence_threshold
        self.urgency_high_threshold = urgency_high_threshold
        self.enabled = enabled

        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._position_callback = None  # Called with action decisions
        self._get_positions_callback = None  # Returns current positions

    def start(
        self,
        get_positions_fn,
        action_callback: callable
    ):
        """
        Start monitoring positions.

        Args:
            get_positions_fn: Function that returns list of open positions
            action_callback: Function called with MonitorResult decisions
        """
        if self._monitoring:
            print("[PositionMonitor] Already running")
            return

        self._get_positions_callback = get_positions_fn
        self._position_callback = action_callback
        self._monitoring = True

        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True
        )
        self._monitor_thread.start()
        print(f"[PositionMonitor] Started with {self.check_interval}s interval")

    def stop(self):
        """Stop monitoring positions."""
        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        print("[PositionMonitor] Stopped")

    def check_now(self, positions: Optional[List[dict]] = None) -> Dict[int, MonitorResult]:
        """
        Trigger an immediate check of positions.

        Args:
            positions: Optional pre-fetched positions, otherwise uses callback

        Returns:
            Dict mapping trade_id to MonitorResult
        """
        if positions is None and self._get_positions_callback:
            positions = self._get_positions_callback()

        if not positions:
            return {}

        results = {}
        for pos in positions:
            result = self._analyze_position(pos, positions)
            results[pos.get("trade_id")] = result

            # Execute callback if provided
            if self._position_callback:
                self._position_callback(pos, result)

        return results

    def _monitor_loop(self):
        """Main monitoring loop."""
        while self._monitoring:
            try:
                positions = self._get_positions_callback() if self._get_positions_callback else []
                if positions:
                    self.check_now(positions)
            except Exception as e:
                print(f"[PositionMonitor] Error in loop: {e}")

            time.sleep(self.check_interval)

    def _analyze_position(
        self,
        position: dict,
        all_positions: List[dict]
    ) -> MonitorResult:
        """Analyze a single position."""
        start_time = time.time()

        symbol = position.get("symbol", "")
        market_context = self.brain.get_market_context(symbol)

        # Build recent candles - this would come from candle aggregator
        # For now, placeholder - would integrate with existing candle data
        recent_candles = position.get("recent_candles", [])

        prompt = position_monitor_prompt(
            position_data=position,
            market_context=market_context,
            recent_candles=recent_candles,
            open_trade_history=all_positions
        )

        try:
            response = self.ai.generate(
                prompt=prompt,
                system=POSITION_MONITOR_SYSTEM,
                max_tokens=2048,
                temperature=0.3
            )

            result = self._parse_response(response)
            result.latency_ms = (time.time() - start_time) * 1000

            # Update Brain
            self._update_brain(position, result)

            return result

        except Exception as e:
            print(f"[PositionMonitor] Error analyzing position: {e}")
            return MonitorResult(
                action=PositionAction.HOLD,
                confidence=0.0,
                reasoning=f"Error: {str(e)}",
                urgency="low",
                new_stop_loss=None,
                new_take_profit=None,
                close_percentage=0.0,
                warnings=[str(e)],
                latency_ms=(time.time() - start_time) * 1000,
                provider="error"
            )

    def _parse_response(self, response: AIResponse) -> MonitorResult:
        """Parse AI response into MonitorResult."""
        data = self.ai.extract_json(response)

        if data:
            try:
                action_str = data.get("action", "HOLD").upper()
                action = PositionAction[action_str]
            except KeyError:
                action = PositionAction.HOLD

            return MonitorResult(
                action=action,
                confidence=float(data.get("confidence", 0.5)),
                reasoning=str(data.get("reasoning", "")),
                urgency=data.get("urgency", "low"),
                new_stop_loss=data.get("new_stop_loss"),
                new_take_profit=data.get("new_take_profit"),
                close_percentage=float(data.get("close_percentage", 0.0)),
                warnings=data.get("warnings", []),
                latency_ms=response.latency_ms,
                provider=response.provider.value
            )

        # Fallback
        return MonitorResult(
            action=PositionAction.HOLD,
            confidence=0.5,
            reasoning=response.content[:500],
            urgency="low",
            new_stop_loss=None,
            new_take_profit=None,
            close_percentage=0.0,
            warnings=[],
            latency_ms=response.latency_ms,
            provider=response.provider.value
        )

    def _update_brain(self, position: dict, result: MonitorResult):
        """Update Brain with monitoring analysis."""
        try:
            prompt = brain_update_prompt(
                action=result.action.value,
                trade_data=position,
                ai_reasoning=result.reasoning,
                outcome="monitoring"
            )
            self.brain.add_memory(
                content=prompt,
                memory_type="position_monitor",
                metadata={
                    "symbol": position.get("symbol"),
                    "strategy_name": position.get("strategy_name"),  # May be None for OANDA trades
                    "action": result.action.value,
                    "confidence": result.confidence,
                    "urgency": result.urgency
                }
            )
        except Exception as e:
            print(f"[PositionMonitor] Failed to update Brain: {e}")

    def should_act(self, result: MonitorResult) -> bool:
        """Check if action should be executed based on thresholds."""
        if not result or result.confidence < self.confidence_threshold:
            return False

        # High urgency actions need higher confidence
        if result.urgency == "high" and result.confidence < self.urgency_high_threshold:
            return False

        return result.action != PositionAction.HOLD


# Singleton instance
_monitor: Optional[PositionMonitor] = None


def get_position_monitor() -> PositionMonitor:
    """Get or create the position monitor singleton."""
    global _monitor
    if _monitor is None:
        _monitor = PositionMonitor()
    return _monitor
