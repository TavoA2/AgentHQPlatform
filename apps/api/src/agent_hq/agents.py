"""Agent registry: the code-side source of truth for agents and their permissions.

Rows in the `agents` table are seeded from here (display data, enabled flag). Tool
permissions are never read from the database or from model output.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_hq.models import Agent


@dataclass(frozen=True)
class AgentDefinition:
    key: str
    display_name: str
    department: str
    model_profile: str
    description: str
    allowed_tools: frozenset[str]
    can_delegate_to: frozenset[str] = frozenset()


KNOWLEDGE_TOOLS = frozenset({"knowledge.search", "knowledge.propose"})

CIO = AgentDefinition(
    key="cio",
    display_name="Dixon",
    department="executive",
    model_profile="reasoning",
    description="AI CIO: coordinates requests, plans work, delegates, verifies and reports.",
    allowed_tools=frozenset({"report.publish_external", "changeset.propose"}) | KNOWLEDGE_TOOLS,
    can_delegate_to=frozenset({"devops", "software_engineer", "qa"}),
)

DEVOPS = AgentDefinition(
    key="devops",
    display_name="DevOps Engineer",
    department="engineering",
    model_profile="reasoning",
    description="Reviews CI/CD and infrastructure configuration (read-only).",
    allowed_tools=frozenset({"github.list_tree", "github.read_file", "github.list_workflow_runs"})
    | KNOWLEDGE_TOOLS,
)

SOFTWARE_ENGINEER = AgentDefinition(
    key="software_engineer",
    display_name="Software Engineer",
    department="engineering",
    model_profile="reasoning",
    description="Designs and writes code changes with tests; proposes them, never pushes.",
    allowed_tools=frozenset({"github.list_tree", "github.read_source"}) | KNOWLEDGE_TOOLS,
)

QA = AgentDefinition(
    key="qa",
    display_name="QA Engineer",
    department="quality",
    model_profile="reasoning",
    description="Plans tests, runs them in the isolated sandbox and reports with evidence.",
    allowed_tools=frozenset({"github.list_tree", "github.read_source", "sandbox.run_tests"})
    | KNOWLEDGE_TOOLS,
)

REGISTRY: dict[str, AgentDefinition] = {a.key: a for a in (CIO, DEVOPS, SOFTWARE_ENGINEER, QA)}


def get_definition(key: str) -> AgentDefinition:
    try:
        return REGISTRY[key]
    except KeyError as exc:
        raise KeyError(f"unknown agent {key!r}") from exc


async def seed_agents(session: AsyncSession) -> None:
    existing = {a.key: a for a in await session.scalars(select(Agent))}
    for definition in REGISTRY.values():
        row = existing.get(definition.key)
        if row is None:
            session.add(
                Agent(
                    key=definition.key,
                    display_name=definition.display_name,
                    department=definition.department,
                    model_profile=definition.model_profile,
                    config={"description": definition.description},
                )
            )
        else:
            row.display_name = definition.display_name
            row.department = definition.department
            row.model_profile = definition.model_profile
            row.config = {**row.config, "description": definition.description}
    await session.flush()


async def agent_ids(session: AsyncSession) -> dict[str, object]:
    return {a.key: a.id for a in await session.scalars(select(Agent))}
