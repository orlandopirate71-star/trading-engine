#!/usr/bin/env python3
"""
Brain Memory Cleanup Script
Deletes all signal validations from the Brain MCP server.
Run every hour via cron to keep the Brain database clean.
"""
import requests
import sys


def cleanup_all_signal_validations(brain_url: str = "http://192.168.0.32:8000"):
    """
    Query Brain for all signal_validation memories and delete all of them.
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
        deleted_count = 0

        print(f"[Cleanup] Found {len(memories)} signal validation memories")

        for memory in memories:
            memory_id = memory.get("id")

            # Delete all signal validations regardless of age/expiry
            delete_response = requests.post(
                f"{brain_url}/delete_memory",
                json={"memory_id": memory_id},
                timeout=10
            )

            if delete_response.status_code == 200:
                deleted_count += 1
                print(f"[Cleanup] Deleted memory {memory_id}")
            else:
                print(f"[Cleanup] Failed to delete {memory_id}: {delete_response.status_code}")

        print(f"[Cleanup] Completed: Deleted {deleted_count} signal validation memories")
        return deleted_count

    except requests.exceptions.RequestException as e:
        print(f"[Cleanup] Failed to connect to Brain: {e}")
        sys.exit(1)


if __name__ == "__main__":
    cleanup_all_signal_validations()
