"""
Fakes shared by the Fase 11 security suite. Each test drives the REAL node /
policy code with a scripted "LLM" (it returns whatever an attacker managed
to make the model say) and a recording MCP client (so a test can assert a
tool was NOT called — the point of most of these tests).
"""


class ScriptedLLM:
    """Returns the given structured results in order; records every prompt."""

    def __init__(self, *results):
        self._results = list(results)
        self.prompts: list[str] = []

    def with_structured_output(self, schema, include_raw=True):
        return self

    async def ainvoke(self, messages):
        self.prompts.append("\n".join(str(m.content) for m in messages))
        result = self._results.pop(0) if len(self._results) > 1 else self._results[0]
        return {"parsed": result, "parsing_error": None}


class RecordingMCP:
    def __init__(self, output: str = '{"status": "success"}'):
        self.calls: list[tuple[str, dict]] = []
        self.catalog_requests: list = []
        self._output = output

    def prompt_catalog(self, only=None, hidden_params=None):
        self.catalog_requests.append(None if only is None else sorted(only))
        names = sorted(only) if only is not None else ["<all>"]
        return "\n".join(f"- {n}()" for n in names)

    async def call_tool(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        return self._output
