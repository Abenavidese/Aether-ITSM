# ADR-006: Dual-Environment LLM Architecture (Ollama & Nebius)

## Status
Accepted

## Context
During the hackathon and normal development cycles, iterating on LangGraph agents can consume a significant amount of tokens due to the loop-heavy nature of agentic execution. If developers run these tests against cloud providers (e.g., Nebius Token Factory, OpenAI) directly, the API costs can scale rapidly. We need a way to develop and test our graphs locally at $0 cost while ensuring 100% compatibility with the production Nebius deployment.

## Decisions

### 1. Abstracting LLM Initialization (`src/config.py`)
**Decision:** We will abstract the instantiation of LLMs into a Factory function in `src/config.py`. The system will read a `USE_OLLAMA` environment variable.
*   If `USE_OLLAMA=True`: The system initializes `ChatOllama` using local models running on the developer's machine.
*   If `USE_OLLAMA=False`: The system initializes `ChatOpenAI` pointing to the Nebius Token Factory `base_url`.

### 2. Standardizing on Structured Output
**Decision:** Because our `AgentState` relies on strict Pydantic schemas (`with_structured_output`), the local Ollama model chosen must natively support Tool Calling or JSON structured outputs (e.g., `llama3.1`, `qwen2.5`).

## Consequences
- **Positive:** Reduces development API costs to strictly $0. Allows developers to test graph routing logic on trains or airplanes without internet.
- **Positive:** Demonstrates to hackathon judges a mature understanding of FinOps (Financial Operations) and Production vs. Dev environment parity.
- **Negative:** Local testing speed depends heavily on the developer's local GPU/RAM compared to the fast Nebius cloud endpoints.
