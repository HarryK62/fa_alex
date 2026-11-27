"""
Alex Researcher Service - Investment Advice Agent
"""

import os
import logging
from datetime import datetime, UTC
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from agents import Agent, RunHooks, Runner, trace

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import from our modules
from context import get_agent_instructions, DEFAULT_RESEARCH_PROMPT
from mcp_servers import create_playwright_mcp_server
from tools import ingest_financial_document

# Load environment before Langfuse reads credentials.
load_dotenv(override=True)

from tracing import observe

app = FastAPI(title="Alex Researcher Service")


MCP_LOGGING_ENABLED = os.getenv("MCP_LOGGING") == "True"


def _trim_for_log(value: Any, max_length: int = 1500) -> str:
    text = str(value)
    if len(text) <= max_length:
        return text
    return f"{text[:max_length]}... [trimmed {len(text) - max_length} chars]"


class ResearchLoggingHooks(RunHooks):
    async def on_tool_start(self, context, agent, tool) -> None:
        if MCP_LOGGING_ENABLED:
            logger.info(
                "[tool:start] name=%s type=%s repr=%s",
                getattr(tool, "name", type(tool).__name__),
                type(tool).__name__,
                _trim_for_log(repr(tool), max_length=500),
            )

    async def on_tool_end(self, context, agent, tool, result) -> None:
        if MCP_LOGGING_ENABLED:
            logger.info(
                "[tool:end] name=%s result=%s",
                getattr(tool, "name", type(tool).__name__),
                _trim_for_log(result),
            )


# Request model
class ResearchRequest(BaseModel):
    topic: Optional[str] = None  # Optional - if not provided, agent picks a topic


async def run_research_agent(topic: str = None) -> str:
    """Run the research agent to generate investment advice."""

    # Prepare the user query
    if topic:
        query = f"Research this investment topic: {topic}"
    else:
        query = DEFAULT_RESEARCH_PROMPT

    if MCP_LOGGING_ENABLED:
        logger.info(
            "Starting research agent topic_provided=%s query_preview=%s",
            bool(topic),
            _trim_for_log(query, max_length=500),
        )

    # OpenAI through the Agents SDK's built-in provider
    model_name = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    model = model_name

    if MCP_LOGGING_ENABLED:
        logger.info(
            "Research agent runtime model=%s playwright_logging=%s",
            model_name,
            os.environ.get("DEBUG"),
        )

    # Create and run the agent with MCP server.
    # Scheduled research has no signed-in user, so this trace is not tied to a user id.
    with observe(
        trace_name="research-market",
        feature="researcher",
        input={"topic": topic or "auto"},
        metadata={"model": model_name},
        tags=["market-research"],
    ) as span:
        with trace("research-market"):
            async with create_playwright_mcp_server(timeout_seconds=120) as playwright_mcp:
                if MCP_LOGGING_ENABLED:
                    logger.info("Playwright MCP server context created")
                agent = Agent(
                    name="Alex Investment Researcher",
                    instructions=get_agent_instructions(),
                    model=model,
                    tools=[ingest_financial_document],
                    mcp_servers=[playwright_mcp],
                )

                try:
                    result = await Runner.run(
                        agent,
                        input=query,
                        max_turns=30,
                        hooks=ResearchLoggingHooks() if MCP_LOGGING_ENABLED else None,
                    )
                except Exception:
                    if MCP_LOGGING_ENABLED:
                        logger.exception("Research agent run failed")
                    raise

                if MCP_LOGGING_ENABLED:
                    logger.info(
                        "Research agent run completed output_preview=%s",
                        _trim_for_log(result.final_output, max_length=1000),
                    )

        span.update(output=result.final_output)
        return result.final_output


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "service": "Alex Researcher",
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@app.post("/research")
async def research(request: ResearchRequest) -> str:
    """
    Generate investment research and advice.

    The agent will:
    1. Browse current financial websites for data
    2. Analyze the information found
    3. Store the analysis in the knowledge base

    If no topic is provided, the agent will pick a trending topic.
    """
    logger.info(f"MCP_LOGGING_ENABLED={MCP_LOGGING_ENABLED}")

    try:
        response = await run_research_agent(request.topic)
        return response
    except Exception as e:
        print(f"Error in research endpoint: {e}")
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/research/auto")
async def research_auto():
    """
    Automated research endpoint for scheduled runs.
    Picks a trending topic automatically and generates research.
    """
    try:
        # Always use agent's choice for automated runs
        response = await run_research_agent(topic=None)
        return {
            "status": "success",
            "timestamp": datetime.now(UTC).isoformat(),
            "message": "Automated research completed",
            "preview": response[:200] + "..." if len(response) > 200 else response,
        }
    except Exception as e:
        print(f"Error in automated research: {e}")
        return {"status": "error", "timestamp": datetime.now(UTC).isoformat(), "error": str(e)}


@app.get("/health")
async def health():
    """Health check."""
    return {
        "service": "Alex Researcher",
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
        "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        "mcp_logging_enabled": MCP_LOGGING_ENABLED,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
