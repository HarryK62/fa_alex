"""
Report Writer Agent - generates portfolio analysis narratives.
"""

import os
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from agents import function_tool, RunContextWrapper

logger = logging.getLogger()

# Money is shown as e.g. AUD$1,234.56 (BASE_CURRENCY plus "$")
MONEY = os.getenv("BASE_CURRENCY", "AUD").strip().upper() + "$"


@dataclass
class ReporterContext:
    """Context for the Reporter agent"""

    job_id: str
    portfolio_data: Dict[str, Any]
    user_data: Dict[str, Any]
    db: Optional[Any] = None  # Database connection (optional for testing)


def calculate_portfolio_metrics(portfolio_data: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate basic portfolio metrics."""
    metrics = {
        "total_value": 0,
        "cash_balance": 0,
        "num_accounts": len(portfolio_data.get("accounts", [])),
        "num_positions": 0,
        "unique_symbols": set(),
    }

    for account in portfolio_data.get("accounts", []):
        metrics["cash_balance"] += float(account.get("cash_balance", 0))
        positions = account.get("positions", [])
        metrics["num_positions"] += len(positions)

        for position in positions:
            symbol = position.get("symbol")
            if symbol:
                metrics["unique_symbols"].add(symbol)

            # Calculate value if we have price
            instrument = position.get("instrument", {})
            if instrument.get("current_price"):
                value = float(position.get("quantity", 0)) * float(instrument["current_price"])
                metrics["total_value"] += value

    metrics["total_value"] += metrics["cash_balance"]
    metrics["unique_symbols"] = len(metrics["unique_symbols"])

    return metrics


def format_portfolio_for_analysis(portfolio_data: Dict[str, Any], user_data: Dict[str, Any]) -> str:
    """Format portfolio data for agent analysis."""
    metrics = calculate_portfolio_metrics(portfolio_data)

    lines = [
        f"Portfolio Overview:",
        f"- {metrics['num_accounts']} accounts",
        f"- {metrics['num_positions']} total positions",
        f"- {metrics['unique_symbols']} unique holdings",
        f"- {MONEY}{metrics['cash_balance']:,.2f} in cash",
        f"- {MONEY}{metrics['total_value']:,.2f} total value" if metrics["total_value"] > 0 else "",
        "",
        "Account Details:",
    ]

    for account in portfolio_data.get("accounts", []):
        name = account.get("name", "Unknown")
        cash = float(account.get("cash_balance", 0))
        lines.append(f"\n{name} ({MONEY}{cash:,.2f} cash):")

        for position in account.get("positions", []):
            symbol = position.get("symbol")
            quantity = float(position.get("quantity", 0))
            instrument = position.get("instrument", {})
            name = instrument.get("name", "")

            price = float(instrument.get("current_price") or 0)
            label = f"{symbol} ({name})" if name and name != symbol else symbol
            lines.append(f"  - {label}: {quantity:,.2f} shares x {MONEY}{price:,.2f} = {MONEY}{quantity * price:,.2f}")

    # Exact allocations worked out in Python, so the report quotes real percentages
    from src.portfolio import compute_allocations, format_allocations

    lines.extend(
        [
            "",
            "Calculated Allocations (exact; quote these figures, do not estimate your own):",
            format_allocations(
                compute_allocations(portfolio_data), os.getenv("BASE_CURRENCY", "AUD").upper()
            ),
        ]
    )

    region_targets = user_data.get("region_targets") or {}
    asset_targets = user_data.get("asset_class_targets") or {}
    if region_targets or asset_targets:
        lines.extend(["", "User Targets:"])
        from src.portfolio import display_name, region_group

        for key, pct in asset_targets.items():
            lines.append(f"- {display_name(key)}: {pct}%")
        for key, pct in region_targets.items():
            lines.append(f"- {region_group(key)}: {pct}%")

    # Add user context
    lines.extend(
        [
            "",
            "User Profile:",
            f"- Years to retirement: {user_data.get('years_until_retirement', 'Not specified')}",
            f"- Target retirement income: {MONEY}{user_data.get('target_retirement_income', 0):,.0f}/year",
        ]
    )

    return "\n".join(lines)


# update_report tool removed - report is now saved directly in lambda_handler


@function_tool
async def get_market_insights(
    wrapper: RunContextWrapper[ReporterContext], symbols: List[str]
) -> str:
    """
    Retrieve market insights from the local knowledge base.

    Args:
        wrapper: Context wrapper with job_id and database
        symbols: List of symbols to get insights for

    Returns:
        Relevant market context and insights
    """
    try:
        # Knowledge base: pgvector + OpenAI embeddings
        from src.vectors import search

        query = f"market analysis {' '.join(symbols[:5])}" if symbols else "market outlook"
        insights = []
        for doc in search(query, top_k=3):
            text = doc.get("text", "")[:200]
            if text:
                company = (doc.get("metadata") or {}).get("company_name", "")
                prefix = f"{company}: " if company else "- "
                insights.append(f"{prefix}{text}...")
        if insights:
            return "Market Insights:\n" + "\n".join(insights)
        return "Market insights unavailable - proceeding with standard analysis."

    except Exception as e:
        logger.warning(f"Reporter: Could not retrieve market insights: {e}")
        return "Market insights unavailable - proceeding with standard analysis."


def create_agent(job_id: str, portfolio_data: Dict[str, Any], user_data: Dict[str, Any], db=None):
    """Create the reporter agent with tools and context."""

    # Get model configuration
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    # Create context
    context = ReporterContext(
        job_id=job_id, portfolio_data=portfolio_data, user_data=user_data, db=db
    )

    # Tools - only get_market_insights now, report saved in lambda_handler
    tools = [get_market_insights]

    # Format portfolio for analysis
    portfolio_summary = format_portfolio_for_analysis(portfolio_data, user_data)

    # Create task
    task = f"""Analyze this investment portfolio and write a comprehensive report.

{portfolio_summary}

Your task:
1. First, get market insights for the top holdings using get_market_insights()
2. Analyze the portfolio's current state, strengths, and weaknesses
3. Generate a detailed, professional analysis report in markdown format

The report should include:
- Executive Summary
- Portfolio Composition Analysis
- Risk Assessment
- Diversification Analysis
- Retirement Readiness (based on user goals)
- Recommendations
- Market Context (from insights)

Provide your complete analysis as the final output in clear markdown format.
Make the report informative yet accessible to a retail investor."""

    return model, tools, task, context
