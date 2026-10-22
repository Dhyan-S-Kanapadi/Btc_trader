"""Throwaway AgentCore hello proof; not imported by trader production code."""

# ponytail: dependencies stay uninstalled until an approved live test; this remains non-production.
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from langgraph.graph import END, START, StateGraph

app = BedrockAgentCoreApp()


def hello_graph() -> object:
    graph = StateGraph(dict)
    graph.add_node("hello", lambda state: {"verdict": {"action": "SKIP", "reason_code": "SPIKE"}})
    graph.add_edge(START, "hello")
    graph.add_edge("hello", END)
    return graph.compile()


@app.entrypoint
def invoke(payload: dict[str, object], _context: object) -> dict[str, object]:
    """Preserves the intended snapshot-to-verdict shape without any trading action."""
    return hello_graph().invoke({"snapshot": payload})


if __name__ == "__main__":
    app.run()
