# ai/api/deps.py
from typing import Generator
from ai.agents.graph import get_graph

async def get_compiled_graph():
    """
    Dependency injection for FastAPI to get the compiled LangGraph instance.
    """
    return get_graph()
