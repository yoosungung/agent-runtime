"""Knowledge binding models shared by BFF and runtimes."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RagBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index_namespace: str
    filter: dict[str, str] = Field(default_factory=dict)


class GraphBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nebula_space: str


class WikiBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vfs_mount: str


class KnowledgeBinding(BaseModel):
    """Resolved pipeline project knowledge boundary."""

    model_config = ConfigDict(extra="forbid")

    tenant: str
    project_id: str
    project_slug: str = ""
    rag: RagBinding
    graph: GraphBinding
    wiki: WikiBinding

    @classmethod
    def from_api_dict(cls, data: dict) -> KnowledgeBinding:
        rag_raw = data.get("rag") or {}
        graph_raw = data.get("graph") or {}
        wiki_raw = data.get("wiki") or {}
        return cls(
            tenant=str(data.get("tenant") or ""),
            project_id=str(data.get("project_id") or ""),
            project_slug=str(data.get("project_slug") or ""),
            rag=RagBinding(
                index_namespace=str(rag_raw.get("index_namespace") or ""),
                filter={
                    str(k): str(v)
                    for k, v in (rag_raw.get("filter") or {}).items()
                },
            ),
            graph=GraphBinding(nebula_space=str(graph_raw.get("nebula_space") or "")),
            wiki=WikiBinding(
                vfs_mount=str(wiki_raw.get("vfs_mount") or ""),
            ),
        )
