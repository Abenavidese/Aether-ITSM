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
        return _BoundScriptedLLM(self, schema)

    async def _answer(self, schema, messages):
        # Results are scripted per output schema: a call for a schema the
        # script has nothing for fails like a model that is down (e.g. the
        # Concierge's supervisor in a test that only scripts the answer), and
        # leaves no trace in `prompts`.
        matching = [r for r in self._results if schema is None or isinstance(r, schema)]
        if not matching:
            raise LookupError(f"ScriptedLLM has no scripted {getattr(schema, '__name__', schema)} result")
        self.prompts.append("\n".join(str(m.content) for m in messages))
        result = matching[0]
        if len(matching) > 1:
            self._results.remove(result)
        return {"parsed": result, "parsing_error": None,
                "raw": AIMessage(content="", usage_metadata=self._usage)}

    async def ainvoke(self, messages):
        return await self._answer(None, messages)


class _BoundScriptedLLM:
    def __init__(self, llm: ScriptedLLM, schema):
        self._llm, self._schema = llm, schema

    async def ainvoke(self, messages):
        return await self._llm._answer(self._schema, messages)


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


def empty_retrieval(*args, **kwargs):
    """Stand-in for src.rag.service.retrieve: the knowledge base found nothing."""
    from src.rag.query import QueryPlan
    from src.rag.retrieval import RetrievalResult
    return RetrievalResult(plan=QueryPlan(original="", semantic="", terms=[], entities=[]))
