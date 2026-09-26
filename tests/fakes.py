"""
Test doubles shared by the whole suite. Tests drive the REAL node / policy /
queue code with a scripted "LLM" (it returns whatever the test — or an
attacker — wants the model to say) and a recording MCP client (so a test can
assert a tool was NOT called).
"""
from langchain_core.messages import AIMessage


class ScriptedLLM:
    """
    Returns the given structured results in order; records every prompt.
    Reports token usage on the raw message like a real chat model does
    (usage_metadata), so tracing/cost code sees realistic data.
    """
    model = "scripted-model"

    def __init__(self, *results, input_tokens: int = 100, output_tokens: int = 20):
        self._results = list(results)
        self.prompts: list[str] = []
        self._usage = {"input_tokens": input_tokens, "output_tokens": output_tokens,
                       "total_tokens": input_tokens + output_tokens}

    def with_structured_output(self, schema, include_raw=True):
        return self

    async def ainvoke(self, messages):
        self.prompts.append("\n".join(str(m.content) for m in messages))
        result = self._results.pop(0) if len(self._results) > 1 else self._results[0]
        return {"parsed": result, "parsing_error": None,
                "raw": AIMessage(content="", usage_metadata=self._usage)}


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
