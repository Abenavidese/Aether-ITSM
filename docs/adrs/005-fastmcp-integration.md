# ADR-005: Adoption of Real MCP Architecture (FastMCP)

## Status
Accepted

## Context
Initially, the project was planned to use standard Python functions to "mock" the Model Context Protocol (MCP) tool execution in order to accelerate MVP development during the hackathon. However, to truly demonstrate an enterprise-grade "Open Spec" and Agentic architecture, relying on Python mocks weakens the architectural integrity and decoupling of the system.

## Decisions

### 1. Ditching the Mock
**Decision:** We will NOT use local python dictionaries or functions (`mcp_mock.py`) to simulate tools. The mock file has been deleted.

### 2. Adoption of FastMCP (Official SDK)
**Decision:** We will use the official `mcp` Python SDK (specifically the `FastMCP` class) to build a standalone, strictly protocol-compliant MCP Server (`src/tools/mcp_server.py`). 
*   **Why?** FastMCP automatically handles JSON Schema generation, tool capability broadcasting, and standardizes input/output over `stdio`. It perfectly isolates the tool execution logic from the LangGraph agent logic.

### 3. LangGraph as an MCP Client
**Decision:** The LangGraph execution node will instantiate an MCP Client session. When the LLM decides to use a tool, LangGraph will communicate with the `FastMCP` server over a subprocess standard IO connection (`stdio`). 
*   **Why?** This accurately mimics a production deployment where the Agent runs in a Nebius cloud endpoint, and the MCP Server runs in an isolated, highly secure on-premise VPC (NVIDIA OpenShell), communicating via a standardized protocol rather than direct code imports.

## Consequences
- **Positive:** The architecture is now 100% compliant with modern decoupled Agent paradigms. It is a much stronger portfolio piece.
- **Negative:** Increased complexity in the Python code. We must handle async subprocess management and standard IO streaming in LangGraph to communicate with the tool server.
- **Security:** Vastly improved. The LLM logic and the tool execution environment are now physically and logically separated processes.
