#!/usr/bin/env python3
"""
Run all of Alex on this computer. There are no cloud services apart from
OpenAI (models and embeddings), Clerk (sign-in) and Yahoo Finance (prices).

- Postgres + pgvector in Docker holds the app data and the knowledge base
- OpenAI runs the agents (needs OPENAI_API_KEY in the root .env)
- The API runs the planner, which runs the other agents, as local processes

Usage (from the scripts folder):  uv run start_local.py
Press Ctrl+C to stop. The database keeps its data between runs.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
IS_WINDOWS = sys.platform == "win32"


def step(message: str) -> None:
    print(f"\n==> {message}", flush=True)


def fail(message: str) -> None:
    print(f"\nERROR: {message}", flush=True)
    sys.exit(1)


def start_database(env: dict) -> None:
    step("Starting the database (Docker)")
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        fail("Docker is not running. Start Docker Desktop, wait until it says it is running, then try again.")
    if subprocess.run(["docker", "compose", "up", "-d", "--wait"], cwd=ROOT).returncode != 0:
        fail("Could not start the database container. See the Docker output above.")

    count = subprocess.run(
        ["docker", "exec", "fa-alex-postgres", "psql", "-U", "alex", "-d", "alex", "-tAc",
         "SELECT COUNT(*) FROM instruments"],
        capture_output=True, text=True,
    )
    if count.returncode == 0 and count.stdout.strip() not in ("", "0"):
        print(f"    Database ready ({count.stdout.strip()} instruments)")
        return

    step("First run: loading the 22 starter ETFs into the database")
    if subprocess.run(["uv", "run", "seed_data.py"], cwd=ROOT / "backend" / "database", env=env).returncode != 0:
        fail("Loading seed data failed. See the output above.")


def wait_for(url: str, name: str, seconds: int = 120) -> None:
    for _ in range(seconds):
        try:
            httpx.get(url, timeout=2)
            print(f"    {name} running at {url}", flush=True)
            return
        except httpx.HTTPError:
            time.sleep(1)
    fail(f"{name} did not start within {seconds} seconds. See the output above.")


def main() -> None:
    if not (ROOT / ".env").exists():
        fail("The root .env file is missing. It needs OPENAI_API_KEY and the Clerk settings.")
    if not (ROOT / "frontend" / ".env.local").exists():
        fail("frontend/.env.local is missing. It needs your Clerk keys.")

    env = {**os.environ, "PYTHONUTF8": "1"}
    env.pop("VIRTUAL_ENV", None)

    start_database(env)

    processes: list[subprocess.Popen] = []
    try:
        step("Starting the backend API")
        # Output goes straight to this window, so agent logs show here too
        processes.append(subprocess.Popen(["uv", "run", "main.py"], cwd=ROOT / "backend" / "api", env=env))
        wait_for("http://localhost:8000/health", "Backend")

        step("Starting the website")
        frontend = ROOT / "frontend"
        if not (frontend / "node_modules").exists():
            subprocess.run(["npm", "install"], cwd=frontend, check=True, shell=IS_WINDOWS)
        processes.append(subprocess.Popen(["npm", "run", "dev"], cwd=frontend, env=env, shell=IS_WINDOWS))
        wait_for("http://localhost:3000", "Website")

        print("\n" + "=" * 60)
        print("Alex is running locally. Open http://localhost:3000")
        print("Logs appear below. Press Ctrl+C to stop.")
        print("=" * 60 + "\n", flush=True)

        while all(p.poll() is None for p in processes):
            time.sleep(1)
        print("\nA service stopped unexpectedly. See the logs above.")
    except KeyboardInterrupt:
        pass
    finally:
        print("\nStopping Alex...")
        for p in processes:
            if p.poll() is None:
                if IS_WINDOWS:
                    # terminate() would only stop the cmd/uv wrapper, not node or python under it
                    subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
                else:
                    p.terminate()
        for p in processes:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        print("Stopped. The database is still running in Docker; stop it with: docker compose stop")


if __name__ == "__main__":
    main()
