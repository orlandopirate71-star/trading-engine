"""
Brain Client - Interface to Brain MCP server.
Provides trade context, strategy rules, and market reasoning.
"""
import json
import time
import requests
from typing import Optional, Dict, Any, List
from dataclasses import dataclass


@dataclass
class BrainMemory:
    """Represents a piece of information from Brain."""
    id: str
    content: str
    memory_type: str
    relevance_score: float = 0.0


class BrainCache:
    """Simple in-memory cache with TTL for Brain queries."""

    def __init__(self, ttl_seconds: int = 300):  # 5 min default
        self._cache: Dict[str, tuple] = {}  # key -> (result, timestamp)
        self._ttl = ttl_seconds

    def _make_key(self, query: str, memory_types: list = None, limit: int = 10) -> str:
        types_key = ",".join(sorted(memory_types)) if memory_types else ""
        return f"{query}|{types_key}|{limit}"

    def get(self, query: str, memory_types: list = None, limit: int = 10) -> Optional[List[BrainMemory]]:
        key = self._make_key(query, memory_types, limit)
        if key in self._cache:
            result, timestamp = self._cache[key]
            if time.time() - timestamp < self._ttl:
                return result
            del self._cache[key]
        return None

    def set(self, query: str, memory_types: list, limit: int, result: List[BrainMemory]):
        key = self._make_key(query, memory_types, limit)
        self._cache[key] = (result, time.time())

    def clear(self):
        self._cache.clear()


class BrainClient:
    """
    Client for the Brain MCP server at 192.168.0.32:8000.
    Used to query strategy rules, market context, and trade reasoning.
    """

    def __init__(self, base_url: str = "http://192.168.0.32:8000", cache_ttl: int = 300):
        self.base_url = base_url
        self.session = requests.Session()
        self.cache = BrainCache(ttl_seconds=cache_ttl)

    def query(
        self,
        query: str,
        memory_types: Optional[List[str]] = None,
        limit: int = 10
    ) -> List[BrainMemory]:
        """
        Query Brain for relevant memories (with 5-min caching).
        """
        # Check cache first
        cached = self.cache.get(query, memory_types, limit)
        if cached is not None:
            return cached

        try:
            response = self.session.post(
                f"{self.base_url}/search_memory",
                json={
                    "query": query,
                    "limit": limit
                },
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            memories = []
            for item in data.get("results", []):
                memories.append(BrainMemory(
                    id=item.get("id", ""),
                    content=item.get("content", ""),
                    memory_type=item.get("type", "unknown"),
                    relevance_score=item.get("score", 0.0)
                ))

            # Cache the result
            self.cache.set(query, memory_types, limit, memories)
            return memories

        except requests.exceptions.RequestException as e:
            print(f"[Brain] Query failed: {e}")
            return []

    def get_strategy_context(self, strategy_name: str) -> str:
        """
        Get full context for a strategy from Brain.

        Returns strategy rules, parameters, and reasoning.
        """
        memories = self.query(
            f"strategy {strategy_name} rules parameters reasoning",
            memory_types=["strategy"],
            limit=5
        )

        if not memories:
            return f"No Brain context found for strategy: {strategy_name}"

        # Format as context string
        context_parts = [f"=== Strategy: {strategy_name} ==="]
        for mem in memories:
            context_parts.append(f"\n[{mem.memory_type}]\n{mem.content}")

        return "\n".join(context_parts)

    def get_market_context(self, symbol: str, timeframe: str = "H1") -> str:
        """
        Get market context for a symbol from Brain.
        Includes trend analysis, key levels, and recent events.
        """
        memories = self.query(
            f"{symbol} {timeframe} market context trend analysis",
            memory_types=["market_context", "analysis", "trading"],
            limit=5
        )

        if not memories:
            return f"No Brain context for {symbol} {timeframe}"

        context_parts = [f"=== Market Context: {symbol} ({timeframe}) ==="]
        for mem in memories:
            context_parts.append(f"\n[{mem.memory_type}]\n{mem.content}")

        return "\n".join(context_parts)

    def add_memory(
        self,
        content: str,
        memory_type: str = "trading",
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Add a new memory to Brain.

        Returns True if successful.
        """
        try:
            response = self.session.post(
                f"{self.base_url}/save_memory",
                json={
                    "text": content,
                    "type": memory_type,
                    "metadata": metadata or {}
                },
                timeout=10
            )
            response.raise_for_status()
            return True

        except requests.exceptions.RequestException as e:
            print(f"[Brain] Add memory failed: {e}")
            return False

    def update_trade_analysis(
        self,
        trade_id: int,
        analysis: str,
        outcome: str = "pending"
    ) -> bool:
        """
        Update Brain with trade analysis result.

        Stores the AI's reasoning for future reference.
        """
        return self.add_memory(
            content=f"Trade #{trade_id} Analysis: {analysis} | Outcome: {outcome}",
            memory_type="trade_analysis",
            metadata={"trade_id": trade_id, "outcome": outcome}
        )


# Singleton instance
_brain_client: Optional[BrainClient] = None


def get_brain_client() -> BrainClient:
    """Get or create the Brain client singleton."""
    global _brain_client
    if _brain_client is None:
        _brain_client = BrainClient()
    return _brain_client
