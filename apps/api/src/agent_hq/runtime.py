"""Dependencies shared by the worker, graphs and tools."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_hq.config import Settings
from agent_hq.integrations.github import GitHubClient
from agent_hq.integrations.reports import ReportPublisher
from agent_hq.llm.router import ModelRouter


@dataclass
class Runtime:
    settings: Settings
    sessionmaker: async_sessionmaker[AsyncSession]
    models: ModelRouter
    github: GitHubClient
    publisher: ReportPublisher
