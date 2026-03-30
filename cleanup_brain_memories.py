#!/usr/bin/env python3
"""
Brain Memory Cleanup Script
Deletes expired signal validations from the Brain MCP server.
Run this daily via cron to keep the Brain database clean.
"""
import requests
from datetime import datetime
import sys


def cleanup_expired_memories(brain_url: str = "http://192.168.0.32:8000"):
    """
    Query Brain for all signal_validation memories and delete expired ones.
    """
    try:
        # Search for all signal validations
        response = requests.post(
            f"{brain_url}/search_memory",
            json={
                "query": "signal_validation",
                "limit": 1000  # Get all signal validations
            },
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        
        memories = data.get("results", [])
        now = datetime.utcnow()
        deleted_count = 0
        
        print(f"[Cleanup] Found {len(memories)} signal validation memories")
        
        for memory in memories:
            memory_id = memory.get("id")
            metadata = memory.get("metadata", {})
            expires_at_str = metadata.get("expires_at")
            
            if not expires_at_str:
                # No expiry set, skip
                continue
            
            try:
                expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
                
                if now > expires_at:
                    # Memory has expired, delete it
                    delete_response = requests.post(
                        f"{brain_url}/delete_memory",
                        json={"memory_id": memory_id},
                        timeout=10
                    )
                    
                    if delete_response.status_code == 200:
                        deleted_count += 1
                        print(f"[Cleanup] Deleted expired memory {memory_id}")
                    else:
                        print(f"[Cleanup] Failed to delete {memory_id}: {delete_response.status_code}")
                        
            except (ValueError, AttributeError) as e:
                print(f"[Cleanup] Error parsing expiry for {memory_id}: {e}")
                continue
        
        print(f"[Cleanup] Completed: Deleted {deleted_count} expired memories")
        return deleted_count
        
    except requests.exceptions.RequestException as e:
        print(f"[Cleanup] Failed to connect to Brain: {e}")
        sys.exit(1)


if __name__ == "__main__":
    cleanup_expired_memories()
