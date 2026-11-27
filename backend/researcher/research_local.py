#!/usr/bin/env python3
"""
Run the researcher once on this machine.

It browses the web with Chrome, writes a short analysis with OpenAI and saves it
to the local knowledge base through the local Alex API, so Alex must be running
(scripts/start_local.py) in another window.

Usage (from backend/researcher):
    uv run research_local.py                      # the agent picks a topic
    uv run research_local.py "Nvidia stock outlook"
"""

import asyncio
import sys

import httpx

from server import run_research_agent


def main() -> None:
    try:
        httpx.get("http://localhost:8000/health", timeout=3)
    except httpx.HTTPError:
        print("The local Alex API isn't running. Start it first with: uv run start_local.py (in the scripts folder)")
        sys.exit(1)

    topic = " ".join(sys.argv[1:]) or None
    print(f"Researching: {topic or 'a topic the agent picks'} (this takes a minute or two)...")
    result = asyncio.run(run_research_agent(topic))
    print("\n" + result)


if __name__ == "__main__":
    main()
