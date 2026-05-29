import os
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # ── API Keys ─────────────────────────────────────────────────────────────
    cohere_api_key: str = Field(..., validation_alias="COHERE_API_KEY")
    deepseek_api_key: str = Field(..., validation_alias="DEEPSEEK_API_KEY")

    # Google Gemini — dùng cho Orchestrator (structured output native)
    google_api_key: str = Field(..., validation_alias="GEMINI_API_KEY")

    # BrightData — optional, fallback sang os.getenv nếu không set
    brightdata_token: str | None = Field(None, validation_alias="BRIGHTDATA_TOKEN")

    # ── Models ───────────────────────────────────────────────────────────────
    # Orchestrator dùng Gemini vì hỗ trợ response_schema Pydantic native tốt nhất
    orchestrator_model: str = Field(
        "gemini-2.0-flash",
        validation_alias="ORCHESTRATOR_MODEL"
    )
    # DeepSeek cho các agent còn lại (OpenAI-compatible API)
    deepseek_model_default: str = Field(
        "deepseek-v4-flash",
        validation_alias="DEEPSEEK_MODEL_DEFAULT"
    )
    deepseek_model_hard: str = Field(
        "deepseek-v4-pro",
        validation_alias="DEEPSEEK_MODEL_HARD"
    )
    analyst_model: str = "deepseek-v4-flash"
    sanction_model: str = "gemini-2.0-flash"  # Gemini nhanh hơn DeepSeek 5-8x cho structured output
    answer_generate_model: str = Field(
        "gemini-2.0-flash",
        validation_alias="ANSWER_GENERATE_MODEL"
    )  # Model cho AnswerGenerateAgent - dễ dàng thay đổi ngoài code

    # ── Vector Store (Qdrant Local) ──────────────────────────────────────────
    qdrant_path: str = Field(
        os.path.join("data-ingestion", "qdrant_db"),
        validation_alias="QDRANT_PATH"
    )
    qdrant_url: str | None = Field(
        None,
        validation_alias="QDRANT_URL"
    )
    qdrant_collection: str = "traffic_law_final"
    parent_dict_path: str = Field("", validation_alias="PARENT_DICT_PATH")

    # ── Retrieval Tuning ─────────────────────────────────────────────────────
    # Số tài liệu tối đa lấy từ local KB mỗi lần search
    knowledge_top_k: int = Field(5, validation_alias="KNOWLEDGE_TOP_K")
    # Ngưỡng score tối thiểu của local KB — nếu thấp hơn sẽ fallback sang web
    score_threshold: float = Field(0.4, validation_alias="SCORE_THRESHOLD")

    # ── Web Search (BrightData MCP) ──────────────────────────────────────────
    # Số URL tối đa scrape song song sau SERP
    web_scrape_limit: int = Field(3, validation_alias="WEB_SCRAPE_LIMIT")
    # Giới hạn ký tự nội dung mỗi trang để tránh tràn context window LLM
    web_content_max_chars: int = Field(3000, validation_alias="WEB_CONTENT_MAX_CHARS")

    # ── Infrastructure ───────────────────────────────────────────────────────
    database_url: str | None = Field(None, validation_alias="DATABASE_URL")
    redis_url: str | None = Field(None, validation_alias="REDIS_URL")
    redis_conversation_ttl: int = Field(3600, validation_alias="REDIS_CONVERSATION_TTL")  # seconds
    redis_max_history: int = Field(20, validation_alias="REDIS_MAX_HISTORY")  # max messages kept
    max_retries: int = Field(2, validation_alias="MAX_RETRIES")
    max_knowledge_loops: int = Field(15, validation_alias="MAX_KNOWLEDGE_LOOPS")


settings = Settings()
