"""OpenJarvis delegation plugin for Hermes Agent.

Registers the ``openjarvis_ask`` tool (toolset ``openjarvis``) so the Hermes
agent can delegate tasks to the local OpenJarvis agent.
"""


def register(ctx) -> None:
    """Gateway/agent load path: register the OpenJarvis tools."""
    from . import tools

    tools.register_tools(ctx)
def on_pre_gateway_dispatch(ctx, message) -> str | None:
    text = str(message).strip()
    if not text.startswith("/jarvis"):
        return None
    query = text[len("/jarvis"):].lstrip()
    if not query:
        return "Usage: /jarvis <your question>"
    from . import tools
    return tools.openjarvis_ask({"message": query})
