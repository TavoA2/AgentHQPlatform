import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from agent_hq.api.deps import DbDep, PrincipalDep
from agent_hq.api.schemas import (
    GitHubIntegrationIn,
    IntegrationOut,
    ProjectDetailOut,
    ProjectIn,
    ProjectOut,
)
from agent_hq.events import record_audit
from agent_hq.models import Integration, Project

router = APIRouter(prefix="/projects", tags=["projects"])

GITHUB_SECRET_REF = "AGENT_HQ_GITHUB_TOKEN"  # noqa: S105 - name of the env var, not a value


@router.get("")
async def list_projects(_: PrincipalDep, db: DbDep) -> list[ProjectOut]:
    rows = await db.scalars(select(Project).order_by(Project.created_at.desc()))
    return [ProjectOut.model_validate(p) for p in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectIn, principal: PrincipalDep, db: DbDep) -> ProjectOut:
    project = Project(**body.model_dump(), owner_id=principal.user.id)
    db.add(project)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "project key already exists") from exc
    await record_audit(
        db,
        actor_type="user",
        actor_id=str(principal.user.id),
        action="project.created",
        project_id=project.id,
        resource_type="project",
        resource_id=project.id,
        details={"key": project.key},
    )
    await db.commit()
    return ProjectOut.model_validate(project)


async def _get_project(db: DbDep, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    return project


@router.get("/{project_id}")
async def get_project(project_id: uuid.UUID, _: PrincipalDep, db: DbDep) -> ProjectDetailOut:
    project = await _get_project(db, project_id)
    integrations = await db.scalars(select(Integration).where(Integration.project_id == project.id))
    return ProjectDetailOut(
        **ProjectOut.model_validate(project).model_dump(),
        integrations=[IntegrationOut.model_validate(i) for i in integrations],
    )


@router.put("/{project_id}/integrations/github")
async def set_github_integration(
    project_id: uuid.UUID, body: GitHubIntegrationIn, principal: PrincipalDep, db: DbDep
) -> IntegrationOut:
    """Authorize repositories for this project. Read-only access (ADR-0008)."""
    project = await _get_project(db, project_id)
    integration = await db.scalar(
        select(Integration).where(
            Integration.project_id == project.id, Integration.provider == "github"
        )
    )
    if integration is None:
        integration = Integration(
            project_id=project.id,
            provider="github",
            name="default",
            secret_ref=GITHUB_SECRET_REF,
            scopes=["contents:read", "metadata:read", "actions:read"],
        )
        db.add(integration)
    integration.config = {"allowed_repos": body.allowed_repos}
    await db.flush()
    await record_audit(
        db,
        actor_type="user",
        actor_id=str(principal.user.id),
        action="integration.github_repos_set",
        project_id=project.id,
        resource_type="integration",
        resource_id=integration.id,
        details={"allowed_repos": body.allowed_repos},
    )
    await db.commit()
    return IntegrationOut.model_validate(integration)
