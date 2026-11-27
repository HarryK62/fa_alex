"""
Chart Maker Agent - creates visualization data for portfolio analysis.
"""

import os
import logging
from typing import Dict, Any


from templates import CHARTER_INSTRUCTIONS, create_charter_task

logger = logging.getLogger()


def analyze_portfolio(portfolio_data: Dict[str, Any]) -> str:
    """
    Work out the portfolio's composition in Python (values and percentages),
    so the agent only has to turn exact numbers into charts.
    """
    from src.portfolio import compute_allocations, format_allocations

    allocations = compute_allocations(portfolio_data)
    return "Portfolio Analysis:\n" + format_allocations(
        allocations, os.getenv("BASE_CURRENCY", "AUD").upper()
    )


def create_agent(job_id: str, portfolio_data: Dict[str, Any], db=None):
    """Create the charter agent without tools - will output JSON directly."""
    
    # Get model configuration
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    
    # Analyze the portfolio upfront
    portfolio_analysis = analyze_portfolio(portfolio_data)
    logger.info(f"Charter: Portfolio analysis generated, length: {len(portfolio_analysis)}")
    
    # Create the task using template
    task = create_charter_task(portfolio_analysis, portfolio_data)
    
    logger.info(f"Charter: Task created, length: {len(task)} characters")
    
    # Return model and task (no tools or context needed)
    return model, task