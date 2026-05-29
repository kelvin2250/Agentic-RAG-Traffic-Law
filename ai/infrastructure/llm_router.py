# ai/infrastructure/llm_router.py
import logging
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from .config import settings

logger = logging.getLogger(__name__)

# Temperature map theo vai trò — không hardcode trong function
_TEMPERATURE_MAP: dict[str, float] = {
    settings.analyst_model: 0.2,   # Analyst cần suy luận có tính sáng tạo nhẹ
}


def get_llm(model_name: str) -> BaseChatModel:
    """
    Factory: Trả về LLM instance phù hợp theo tên model.
    Hỗ trợ: Gemini (google-genai), DeepSeek (OpenAI-compatible).
    """
    temperature = _TEMPERATURE_MAP.get(model_name, 0.0)

    if "gemini" in model_name.lower():
        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=settings.google_api_key,   # ← đúng field từ config
            temperature=temperature,
            max_retries=settings.max_retries,
        )
    elif "deepseek" in model_name.lower():
        # DeepSeek tương thích hoàn toàn với OpenAI API
        return ChatOpenAI(
            model=model_name,
            api_key=settings.deepseek_api_key,
            base_url="https://api.deepseek.com/v1",
            temperature=temperature,
            max_retries=settings.max_retries,
        )
    else:
        raise ValueError(
            f"Model '{model_name}' không được hỗ trợ. "
            f"Chỉ hỗ trợ: gemini-*, deepseek-*"
        )