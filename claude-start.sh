#!/bin/bash
# Claude Code with Ollama backend - Trading Station
# Usage: ./claude-start.sh [optional claude args]

export ANTHROPIC_BASE_URL="http://192.168.0.35:11434"
export ANTHROPIC_AUTH_TOKEN="ollama"

claude --model minimax-m2.7:cloud "$@"
