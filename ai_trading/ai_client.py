"""
AI Client for Ollama and Anthropic APIs.
Handles LLM inference for trade validation and monitoring.
"""
import json
import time
import requests
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum


class Provider(Enum):
    OLLAMA = "ollama"
    ANTHROPIC = "anthropic"


@dataclass
class AIResponse:
    content: str
    provider: Provider
    model: str
    latency_ms: float
    raw: Optional[dict] = None


class AIClient:
    """
    Unified AI client supporting Ollama (local) and Anthropic (cloud).
    Falls back from primary to secondary if one fails.
    """

    def __init__(
        self,
        primary: Provider = Provider.OLLAMA,
        ollama_base: str = "http://localhost:11434",
        ollama_model: str = "gpt-oss:120b-cloud",  # Default to cloud model
        ollama_backup_base: Optional[str] = None,  # Backup Ollama server
        ollama_backup_model: str = "gpt-oss:120b-cloud",  # Backup model
        anthropic_api_key: Optional[str] = None,
        anthropic_model: str = "claude-sonnet-4-20250514"
    ):
        self.primary = primary
        self.ollama_base = ollama_base
        self.ollama_model = ollama_model
        self.ollama_backup_base = ollama_backup_base
        self.ollama_backup_model = ollama_backup_model
        self.anthropic_api_key = anthropic_api_key
        self.anthropic_model = anthropic_model

        # Track which provider was last used
        self._last_successful: Optional[Provider] = None
        self._using_backup = False

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        timeout: float = 180.0
    ) -> AIResponse:
        """
        Generate a response using the primary provider with fallback.
        """
        start_time = time.time()

        # Try primary first
        if self.primary == Provider.OLLAMA:
            try:
                return self._ollama_generate(
                    prompt, system, max_tokens, temperature, timeout
                )
            except Exception as e:
                print(f"[AI] Primary Ollama failed: {e}")
                
                # Try backup Ollama server if configured
                if self.ollama_backup_base:
                    try:
                        print(f"[AI] Trying backup Ollama server at {self.ollama_backup_base}...")
                        return self._ollama_generate(
                            prompt, system, max_tokens, temperature, timeout,
                            base_override=self.ollama_backup_base,
                            model_override=self.ollama_backup_model
                        )
                    except Exception as backup_e:
                        print(f"[AI] Backup Ollama failed: {backup_e}")
                
                # Try Anthropic as next fallback
                if self.anthropic_api_key:
                    print(f"[AI] Trying Anthropic...")
                    try:
                        return self._anthropic_generate(
                            prompt, system, max_tokens, temperature, timeout
                        )
                    except Exception as anthropic_e:
                        print(f"[AI] Anthropic failed: {anthropic_e}")

        # Try Anthropic as fallback
        if self.primary == Provider.ANTHROPIC and self.anthropic_api_key:
            try:
                return self._anthropic_generate(
                    prompt, system, max_tokens, temperature, timeout
                )
            except Exception as e:
                print(f"[AI] Anthropic failed: {e}")

        # Try secondary Ollama if primary was Anthropic
        if self.primary == Provider.ANTHROPIC:
            try:
                return self._ollama_generate(
                    prompt, system, max_tokens, temperature, timeout
                )
            except Exception as e:
                print(f"[AI] Ollama fallback failed: {e}")
                
                # Try backup Ollama as last resort
                if self.ollama_backup_base:
                    try:
                        print(f"[AI] Trying backup Ollama server at {self.ollama_backup_base}...")
                        return self._ollama_generate(
                            prompt, system, max_tokens, temperature, timeout,
                            base_override=self.ollama_backup_base,
                            model_override=self.ollama_backup_model
                        )
                    except Exception as backup_e:
                        print(f"[AI] Backup Ollama failed: {backup_e}")

        raise RuntimeError(f"All AI providers failed")

    def _ollama_generate(
        self,
        prompt: str,
        system: Optional[str],
        max_tokens: int,
        temperature: float,
        timeout: float,
        model_override: Optional[str] = None,
        base_override: Optional[str] = None
    ) -> AIResponse:
        """Generate using Ollama API."""
        start_time = time.time()
        model = model_override or self.ollama_model
        base_url = base_override or self.ollama_base

        # Build messages format for chat endpoint
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = requests.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens
                }
            },
            timeout=timeout
        )
        response.raise_for_status()

        data = response.json()
        content = data["message"]["content"]

        latency_ms = (time.time() - start_time) * 1000
        self._last_successful = Provider.OLLAMA
        
        # Track if using backup
        if base_override:
            self._using_backup = True
            print(f"[AI] Backup Ollama ({model}): {latency_ms:.0f}ms")
        else:
            self._using_backup = False
            print(f"[AI] Ollama ({model}): {latency_ms:.0f}ms")

        return AIResponse(
            content=content,
            provider=Provider.OLLAMA,
            model=model,
            latency_ms=latency_ms,
            raw=data
        )

    def _anthropic_generate(
        self,
        prompt: str,
        system: Optional[str],
        max_tokens: int,
        temperature: float,
        timeout: float
    ) -> AIResponse:
        """Generate using Anthropic API."""
        start_time = time.time()

        headers = {
            "x-api-key": self.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        body = {
            "model": self.anthropic_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}]
        }

        if system:
            body["system"] = system

        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=body,
            timeout=timeout
        )
        response.raise_for_status()

        data = response.json()
        content = data["content"][0]["text"]

        latency_ms = (time.time() - start_time) * 1000
        self._last_successful = Provider.ANTHROPIC

        print(f"[AI] Anthropic ({self.anthropic_model}): {latency_ms:.0f}ms")

        return AIResponse(
            content=content,
            provider=Provider.ANTHROPIC,
            model=self.anthropic_model,
            latency_ms=latency_ms,
            raw=data
        )

    def extract_json(self, response: AIResponse) -> Optional[Dict[str, Any]]:
        """Extract JSON from response content."""
        content = response.content.strip()

        # Try direct JSON parse
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Try to find JSON in code blocks
        import re
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find JSON object at start
        start = content.find('{')
        end = content.rfind('}') + 1
        if start >= 0 and end > start:
            try:
                return json.loads(content[start:end])
            except json.JSONDecodeError:
                pass

        return None


# Singleton instance
_ai_client: Optional[AIClient] = None


def get_ai_client() -> AIClient:
    """Get or create the AI client singleton."""
    global _ai_client
    if _ai_client is None:
        _ai_client = AIClient()
    return _ai_client


def init_ai_client(
    primary: Provider = Provider.OLLAMA,
    **kwargs
) -> AIClient:
    """Initialize the AI client with settings."""
    global _ai_client
    _ai_client = AIClient(primary=primary, **kwargs)
    return _ai_client
