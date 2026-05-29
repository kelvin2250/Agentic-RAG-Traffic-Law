# ai/agents/base.py
from abc import ABC, abstractmethod
from ai.infrastructure.llm_router import get_llm
from ai.agents.state import AgentState


class BaseAgent(ABC):
    """
    Abstract Base Class cho toàn bộ Agent Node trong hệ thống.
    Ép buộc các Agent con tuân thủ interface LangGraph Node.
    """
    def __init__(self, model_name: str, system_prompt: str):
        self.llm = get_llm(model_name)
        self.system_prompt = system_prompt

    @abstractmethod
    async def __call__(self, state: AgentState) -> dict:
        """
        LangGraph Node interface.

        Args:
            state: AgentState hiện tại.
        Returns:
            dict chứa các fields AgentState cần cập nhật.
        """
        raise NotImplementedError("Bắt buộc override __call__ ở lớp Agent con.")