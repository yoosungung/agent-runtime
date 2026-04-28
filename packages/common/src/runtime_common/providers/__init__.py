"""Infrastructure providers — config + secrets → framework-native infra objects.

Each submodule targets one runtime kind. All imports of framework deps
(langgraph, google-adk, fastmcp, mcp) happen lazily inside builder functions
so a pool image without that framework still loads the module without error.

Usage from a bundle factory:

    from runtime_common.providers.langgraph import build_checkpointer

    def factory(cfg, secrets):
        graph = StateGraph(...)
        ...
        return graph.compile(checkpointer=build_checkpointer(cfg, secrets))
"""
