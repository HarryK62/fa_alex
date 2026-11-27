"""
Run one agent's lambda_handler on this machine.

The API and the planner start each agent with:
    uv run --directory backend/<agent> python ../local_runner.py
with the event JSON on stdin. Running inside the agent's own folder keeps each
agent in its own uv environment. (The entry point keeps its original
lambda_handler name from the AWS version.)
The handler's return value is printed on the last line after RESULT_MARKER.
"""

import json
import logging
import sys
from pathlib import Path

# Show INFO logs; plain Python would hide them without a handler
logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")

RESULT_MARKER = "__ALEX_RESULT__"


def main() -> None:
    sys.path.insert(0, str(Path.cwd()))
    event = json.loads(sys.stdin.read() or "{}")

    from lambda_handler import lambda_handler

    result = lambda_handler(event, None)
    sys.stdout.flush()
    print(RESULT_MARKER + json.dumps(result, default=str), flush=True)


if __name__ == "__main__":
    main()
