# ADR-005: Adoption of Real MCP Architecture (FastMCP)

## Status
Accepted. Implementation status reviewed against the code on 2026-09-26 (roadmap 1.3):
- **Implemented:** a real MCP server (`src/tools/mcp_server.py`, `mcp>=2` `MCPServer`, the
  successor of `FastMCP`) over stdio; one long-lived client per app process
  (`src/agent/mcp_client.py`) that reads the live tool catalog; no mock module.
- **Simulated:** the tool backends. Only `check_service_status` does real work; the VPN, MDM,
  IAM and knowledge-base tools return canned results (`docs/specs/mcp_registry.md`).
- **Planned:** OpenShell isolation. Today the server is a plain local subprocess on the same
  host, so the "physically separated" claim below is the target, not the current state.

## Context
Initially, the project was planned to use standard Python functions to "mock" the Model Context Protocol (MCP) tool execution in order to accelerate MVP development during the hackathon. However, to truly demonstrate an enterprise-grade "Open Spec" and Agentic architecture, relying on Python mocks weakens the architectural integrity and decoupling of the system.

## Decisions

### 1. Ditching the Mock
**Decision:** We will NOT use local python dictionaries or functions (`mcp_mock.py`) to simulate tools. The mock file has been deleted.

### 2. Adoption of FastMCP (Official SDK)
**Decision:** We will use the official `mcp` Python SDK (specifically the `FastMCP` class) to build a standalone, strictly protocol-compliant MCP Server (`src/tools/mcp_server.py`). 
*   **Why?** FastMCP automatically handles JSON Schema generation, tool capability broadcasting, and standardizes input/output over `stdio`. It perfectly isolates the tool execution logic from the LangGraph agent logic.

### 3. LangGraph as an MCP Client
**Decision:** The LangGraph execution node will instantiate an MCP Client session. When the LLM decides to use a tool, LangGraph communicates with the MCP server over a subprocess standard IO connection (`stdio`). 
*   **Why?** This accurately mimics a production deployment where the Agent runs in a Nebius cloud endpoint, and the MCP Server runs in an isolated, highly secure on-premise VPC (NVIDIA OpenShell), communicating via a standardized protocol rather than direct code imports.

## Consequences
- **Positive:** The architecture is now 100% compliant with modern decoupled Agent paradigms. It is a much stronger portfolio piece.
- **Negative:** Increased complexity in the Python code. We must handle async subprocess management and standard IO streaming in LangGraph to communicate with the tool server.
- **Security:** The LLM logic and the tool execution are separate *processes* (Implemented), but on the same host without a sandbox; physical/network isolation depends on OpenShell (Planned). The guarantees that hold today are in code: `src/agent/tool_policy.py` decides every call.
