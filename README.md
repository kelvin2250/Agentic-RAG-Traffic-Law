# 🚦 Agentic RAG Traffic Law Assistant (Vietnam)

**An End-to-End Agentic AI system engineered to decompose and resolve complex, compound traffic law queries in Vietnam. Built with LangGraph for sophisticated agent orchestration, Model Context Protocol (MCP) for modular tool serving, and a robust hybrid search + web fallback retrieval pipeline.**

---

## 📷 Demo

### Login Screen
![Login](img/login.png)

### Chat Interface - Query Input
![Chat Query](img/chat1.png)

### Chat Interface - Response
![Chat Response](img/chat2.png)

---

## 🏗️ Architecture Overview

The system is designed as a microservices architecture, dockerized for ease of development and deployment. 

### System Microservices
```mermaid
graph TD
    User([User]) <--> Frontend[React Frontend - Vite/Nginx]
    Frontend <--> WebBackend[FastAPI Web Backend - Gateway]
    WebBackend <--> Postgres[(PostgreSQL - Chat History)]
    WebBackend <--> RedisCache[(Redis - Cache, Rate Limiting & Short-term Memory)]
    WebBackend <--> AIService[FastAPI AI Service - LangGraph]
    
    AIService <--> RedisCache
    AIService <--> Qdrant[(Qdrant - Vector DB)]
    AIService <--> MCPRetrieval[MCP Retrieval Server - BrightData SERP / Scraper]
    AIService <--> MCPRerank[MCP Rerank Server - Cohere Rerank]
```

### Agentic Workflow (LangGraph StateGraph)
The AI service orchestrates multiple specialized agents using a state machine layout, guaranteeing reliable intent routing, compound query handling, and quality control:

```mermaid
flowchart TD
    Start([🚀 START]) 
    Orchestrator["<b>1. Orchestrator</b><br/>Intent Classification"]
    Knowledge["<b>2. Knowledge Node</b><br/>Sub-query Retrieval Loop"]
    
    GenChat{{"GENERAL_CHAT /<br/>OUT_OF_SCOPE"}}
    Legal{{"LEGAL_CHAT"}}
    SubLoop{{"Next<br/>Sub-query?"}}
    
    RouteGate{{"Route after<br/>Knowledge"}}
    
    Analyst["<b>3. Analyst Agent</b><br/>Behavior Analysis"]
    Sanction["<b>4. Sanction Agent</b><br/>Penalty Extraction"]
    Admin["<b>5. Admin Agent</b><br/>Procedure Steps"]
    
    Validator["<b>6. Validator Node</b><br/>Quality Gate<br/><i>Code-based Checks</i>"]
    
    LoopCorrection{{"Valid?"}}
    
    Synthesizer["<b>7. Synthesizer</b><br/>Final Response"]
    End([✅ END])
    
    Start --> Orchestrator
    Orchestrator --> GenChat
    Orchestrator --> Legal
    
    GenChat -->|Direct Response| Synthesizer
    Legal --> Knowledge
    
    Knowledge --> SubLoop
    SubLoop -->|Next Query| Knowledge
    SubLoop -->|All Done| RouteGate
    
    RouteGate -->|Parallel/<br/>Sequential| Analyst
    RouteGate -->|Parallel/<br/>Sequential| Sanction
    RouteGate -->|Parallel/<br/>Sequential| Admin
    
    Analyst --> Validator
    Sanction --> Validator
    Admin --> Validator
    
    Validator --> LoopCorrection
    
    LoopCorrection -->|✓ Valid| Synthesizer
    LoopCorrection -->|✗ Invalid<br/>Retries Left| Analyst
    LoopCorrection -->|✗ Invalid<br/>Retries Left| Sanction
    LoopCorrection -->|✗ Invalid<br/>Retries Left| Admin
    
    LoopCorrection -->|Max Retries| Synthesizer
    
    Synthesizer --> End
    
    classDef startEnd fill:#10b981,stroke:#059669,stroke-width:2px,color:#fff,font-weight:bold
    classDef process fill:#3b82f6,stroke:#1e40af,stroke-width:2px,color:#fff
    classDef decision fill:#f59e0b,stroke:#d97706,stroke-width:2px,color:#000,font-weight:bold
    classDef validator fill:#8b5cf6,stroke:#6d28d9,stroke-width:2px,color:#fff,font-weight:bold
    classDef synthesizer fill:#06b6d4,stroke:#0891b2,stroke-width:2px,color:#fff,font-weight:bold
    
    class Start,End startEnd
    class Orchestrator,Knowledge,Analyst,Sanction,Admin process
    class GenChat,Legal,SubLoop,RouteGate,LoopCorrection decision
    class Validator validator
    class Synthesizer synthesizer
```
## 🌟 Core AI Engineering Features

### 1. Hierarchical Markdown Chunking & Cost Trade-off
Vietnamese legal documents have strict structures: Chapter (Chương) -> Section (Mục) -> Article (Điều) -> Clause (Khoản) -> Item (Điểm). 

* **Hierarchical Segmentation:** The system utilizes a custom [legal_chunker.py](file:///d:/GenAI/AIAgent/Agentic-RAG-Traffic-Law/ai/util/legal_chunker.py) state machine to parse markdown documents. It extracts **Parent Chunks** (Articles - "Điều") and **Child Chunks** (Clauses - "Khoản" / Items - "Điểm").
* **Metadata Context Injection:** Each retrieved child chunk is dynamically enriched with parent metadata pre-injected at the beginning of the text:
  ```text
  [Điều 6: Xử phạt người điều khiển xe mô tô, xe gắn máy vi phạm quy định] Khoản 4: Phạt tiền từ 800.000 đồng đến 1.000.000 đồng đối với hành vi...
  ```
* **Architectural Trade-off:** Instead of fetching the entire parent document ("Điều") when a child chunk matches (which inflates the LLM context window, wastes tokens, and decreases throughput), the pipeline feeds only the top 5 highly-relevant, context-enriched child chunks directly to the LLM. This delivers superior accuracy while achieving massive token cost savings.

Decree 100/2019/NĐ-CP (Raw Document)
 └── [Parent Context] Article 6 (Điều 6: Xử phạt người đi xe máy...)
      ├── [Child Chunk 1] Clause 4 (Khoản 4: Phạt tiền từ 800k - 1M...)
      │    └── [Metadata Injected Chunk 1] -> Used for Vector Search
      └── [Child Chunk 2] Clause 5 (Khoản 5: Phạt tiền từ 1M - 2M...)
           └── [Metadata Injected Chunk 2] -> Used for Vector Search

### 2. Hybrid Retrieval Pipeline
Combines multiple retrieval strategies to maximize relevance and coverage:
* **Dense Vector Search:** Leverages [Qdrant](https://qdrant.tech/) vector database with semantic embeddings to capture conceptual similarity. Documents are embedded using dense representations, enabling semantic matching beyond keyword overlap.
* **Lexical Keyword Search:** Implements BM25 full-text search to capture exact keyword matches and terminology-specific queries that might be missed by pure semantic search.
* **Hybrid Fusion:** The [hybrid_retrieval.py](file:///d:/GenAI/AIAgent/Agentic-RAG-Traffic-Law/ai/rag/hybrid_retrieval.py) module blends results from both retrieval methods using score normalization and weighted combination, ensuring both semantic and lexical relevance.
* **Cross-Encoder Reranking:** Retrieved candidates are then processed through [Cohere Rerank API](https://cohere.com/) (v3.5), a cross-encoder model that re-scores results based on query-document relevance pairs. This dramatically improves ranking quality compared to separate dense/lexical scores.
* **Adaptive Retrieval Thresholding:** If the reranked relevance score falls below a configurable threshold (`0.3`), the system automatically triggers web search fallback to fetch the latest legal amendments online, ensuring currency and completeness.

### 3. Model Context Protocol (MCP) Integration
Decouples external operations into standalone **MCP Servers** running over SSE Transport:
* **MCP Retrieval Server:** Encapsulates web searching (BrightData SERP API) and webpage markdown extraction (`trafilatura`), isolating scraping overhead.
* **MCP Rerank Server:** Leverages Cohere Rerank API (`rerank-v3.5`) to reorder documents asynchronously.

### 4. Intelligent Query Decomposition & Smart Web Fallback
* **Query Decomposition:** When a compound query is processed (e.g., *"Motorbike carrying 3 people and running a red light fines"*), the Orchestrator splits it into discrete sub-queries (e.g., sub-query 1: motorbike carrying 3 people; sub-query 2: motorbike running red light) and processes them sequentially in a retrieval loop.
* **Score Gatekeeper:** Local search blends Qdrant dense vector retrieval with BM25 lexical keyword matching. If the post-rerank relevance score drops below `0.3`, the system triggers the Web Fallback server to find the latest legal amendments online.

### 5. Self-Correction & Quality Control (Validator Gate)
A dedicated **Validator Node** performs **zero-latency, code-based quality checks** (no LLM calls) on agent outputs before synthesis. It validates citation accuracy and completeness, dynamically manages retry loops, and switches between parallel and sequential processing modes.

**Validation Strategy:**
* **Intent-Specific Checks:**
  - **BEHAVIOR_ANALYSIS:** Ensures legal citations exist (e.g., "Điều 6, Khoản 4") and reasoning (`legal_analysis`) is not empty.
  - **PENALTY_LOOKUP:** Verifies violations include valid legal citations (`legal_basis`) OR a documented reason why no penalties apply (`unresolved_reason`).
  - **ADMIN_PROCEDURE:** Confirms `procedure_name` and `steps` array are populated; checks for source documents in retrieval cache.

* **Adaptive Mode Switching:**
  - **Parallel Mode (Fast Path):** All intents validated simultaneously. If ANY fail, validator switches to Sequential Mode and resets to intent index 0.
  - **Sequential Mode (Recovery Path):** Validates one intent per cycle, re-routes to the corresponding agent for correction, then increments index on success.

* **Retry & Exhaustion Logic:**
  - Each validation failure increments `retry_count` and appends diagnostic errors to state.
  - Upon reaching `max_retries`, the graph proceeds to **Synthesizer** with a disclaimer instead of blocking indefinitely.

---

## 🛠️ Tech Stack & State Design

### Technical Stack
| Layer | Technologies | Key Role |
| :--- | :--- | :--- |
| **Web Gateway** | FastAPI, Uvicorn, PostgreSQL, SQLAlchemy (asyncpg), Redis, JWT | User auth, rate-limiting, conversation storage, and API routing. |
| **Agent Orchestration** | LangGraph, LangChain Core | Multi-agent state preservation, conditional routing, and fallback loops. |
| **LLMs** | Google Gemini (Native Schema Structured Output) | Intent classification and text synthesis, DeepSeek | Situation analysis|
| **Vector DB** | Qdrant, BM25 | Hybrid storage for semantic (embeddings) and lexical search. |
| **Reranking** | Cohere Rerank API (v3.5) | Cross-encoder matching for highly relevant law context retrieval. |
| **External Tools** | FastMCP, SSE Transport, BrightData SERP, Trafilatura | Model Context Protocol implementation for web search & scraping fallbacks. |
| **DevOps** | Docker, Docker Compose, Alembic (DB migration) | Containerization, environment replication, and hot-reloads. |

### LangGraph State Design (`AgentState`)
The global state acts as the single source of truth, managing dynamic routing and custom reducers for list concatenation and deduplication:

```python
class AgentState(TypedDict, total=False):
    # --- Client Metadata
    user_query: str
    session_id: str
    
    # --- Sliding Window Memory & Summary
    conversation_history: Sequence[BaseMessage]
    conversation_summary: str
    
    # --- Orchestrator & Decomposer
    primary_intent: str          # GENERAL_CHAT | OUT_OF_SCOPE | LEGAL_CHAT
    detailed_intents: List[str]  # e.g., ["BEHAVIOR_ANALYSIS", "PENALTY_LOOKUP"]
    is_compound: bool
    sub_queries: List[str]
    current_query_idx: int       # Sub-query tracker for the knowledge loop
    
    # --- Dynamic Graph Routing Plan
    parallel_mode: bool          # Flips to False for sequential recovery on failure
    current_intent_idx: int      # Sequential step tracker
    routing_plan: List[str]
    
    # --- Knowledge retrieval (Accumulated via custom 'merge_docs' Reducer)
    retrieved_docs: Annotated[Sequence[dict], merge_docs]
    retrieval_source: str
    
    # --- Worker outputs
    extracted_facts: dict        # Analyst outputs
    legal_analysis: str          # Analyst analysis
    sanction_details: dict       # Sanction outputs (fine brackets, impounds)
    admin_procedure_details: dict
    final_response: str          # Synthesized markdown result
    
    # --- Error correction & retry limits (Accumulated via custom 'append_errors' Reducer)
    retry_count: int
    max_retries: int
    knowledge_loop_count: int
    validation_report: dict      # Quality metrics check
    errors: Annotated[List[str], append_errors]
```

---

## 📁 Folder Structure

```
Agentic-RAG-Traffic-Law/
├── ai/                      # AI Service (LangGraph Agents)
│   ├── agents/             # Multi-agent orchestration (orchestrator, analyst, sanction, etc.)
│   ├── mcp/                # MCP servers (BrightData, Cohere Rerank)
│   ├── rag/                # Retrieval pipeline (hybrid search, embeddings)
│   ├── infrastructure/      # Config, LLM routing, caching, vector store
│   ├── util/               # Document parsing, legal chunking
│   └── main.py             # FastAPI AI service entry point
├── backend/                 # Web Backend (FastAPI Gateway)
│   ├── app/
│   │   ├── api/            # REST endpoints
│   │   ├── models/         # SQLAlchemy ORM models
│   │   └── crud/           # Database operations
│   └── main.py
├── frontend/               # React UI (Vite)
│   ├── src/
│   └── index.html
├── data/
│   ├── processed/          # Markdown legal documents
│   └── metadata/           # Traffic law metadata
├── data-ingestion/         # Vector DB setup (Qdrant)
├── docker-compose.yml      # Microservices orchestration
└── .env.example            # Configuration template
```

---

## ⚡ Getting Started

### Prerequisites
* Docker & Docker Compose installed.
* API Keys for: Google Gemini, Cohere, BrightData (optional for web fallback).

### Quick Start (Docker Compose)
1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/Agentic-RAG-Traffic-Law.git
   cd Agentic-RAG-Traffic-Law
   ```

2. Create a `.env` file in the root directory:
   ```env
   # LLM API Keys
   GEMINI_API_KEY=your_gemini_api_key
   DEEPSEEK_API_KEY=your_deepseek_api_key
   COHERE_API_KEY=your_cohere_api_key

   # External Tools (Optional)
   BRIGHTDATA_TOKEN=your_brightdata_token

   # DB configs
   POSTGRES_USER=postgres
   POSTGRES_PASSWORD=postgres
   POSTGRES_DB=traffic_law
   DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres-db:5432/traffic_law
   REDIS_URL=redis://redis-cache:6379/0
   QDRANT_URL=http://qdrant-server:6333
   ```

3. Spin up all services using Docker Compose:
   ```bash
   docker-compose up --build
   ```

4. The application services will be available at:
   * **Frontend**: `http://localhost:3000`
   * **Web Backend API**: `http://localhost:8000`
   * **AI Agent Service**: `http://localhost:8001`
   * **Qdrant Dashboard**: `http://localhost:6333/dashboard`
