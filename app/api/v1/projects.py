from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException
from uuid import UUID
from beanie.operators import In

from app.api import deps
from app.models.project import Project, ProjectAssignment
from app.models.user import User
from app.models.notification import Notification
from app.schemas.project import (
    Project as ProjectSchema,
    ProjectCreate,
    ProjectUpdate,
    ProjectAssignmentCreate,
    ProjectAssignmentsUpdate,
    UserProjectAssignmentsUpdate,
)

router = APIRouter()

@router.get("/", response_model=List[ProjectSchema])
async def read_projects(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    if current_user.role.role_name == "USER":
        assignments = await ProjectAssignment.find(ProjectAssignment.user_id == current_user.id).to_list()
        project_ids = [a.project_id for a in assignments]
        
        # If user has assignments, show those. If not, fallback to show all projects 
        # (or at least those marked as global/active) to avoid empty forms.
        if project_ids:
            projects = await Project.find(In(Project.id, project_ids), Project.is_deleted == False).to_list()
        else:
            # Fallback: if no assignments, show all active projects for convenience 
            # unless a strict assignment policy is required.
            projects = await Project.find(Project.is_deleted == False, Project.status == "Active").skip(skip).limit(limit).to_list(length=limit)
    else:
        projects = await Project.find(Project.is_deleted == False).skip(skip).limit(limit).to_list(length=limit)
    return projects

@router.post("/", response_model=ProjectSchema)
async def create_project(
    *,
    project_in: ProjectCreate,
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    project = await Project.find_one(Project.project_code == project_in.project_code)
    if project:
        raise HTTPException(status_code=400, detail="Project with this code already exists.")
        
    db_project = Project(**project_in.model_dump())
    await db_project.insert()
    return db_project

@router.put("/{id}", response_model=ProjectSchema)
async def update_project(
    *,
    id: UUID,
    project_in: ProjectUpdate,
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    project = await Project.find_one(Project.id == id, Project.is_deleted == False)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
        
    update_data = project_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(project, field, value)
        
    await project.save()
    return project

@router.post("/{id}/assign")
async def assign_project(
    *,
    id: UUID,
    assignment_in: ProjectAssignmentCreate,
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    if str(id) != str(assignment_in.project_id):
        raise HTTPException(status_code=400, detail="Project ID mismatch")
        
    existing = await ProjectAssignment.find_one(
        ProjectAssignment.project_id == id, 
        ProjectAssignment.user_id == assignment_in.user_id
    )
    
    if existing:
        return {"msg": "User is already assigned to this project"}
        
    assignment = ProjectAssignment(**assignment_in.model_dump())
    await assignment.insert()

    # Add notification for the assigned user
    target_user = await User.find_one(User.id == assignment_in.user_id)
    project = await Project.find_one(Project.id == id)
    if target_user and project:
        await Notification(
            user=target_user,
            type="info",
            title="New Project Assignment",
            message=f"You have been assigned to project: {project.name} ({project.project_code})",
            link=f"/projects/{project.id}",
        ).insert()

    return {"msg": "Assignment successful"}


@router.get("/assignments")
async def read_project_assignments(
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    projects = await Project.find(Project.is_deleted == False).to_list()
    project_ids = [p.id for p in projects]
    assignments = await ProjectAssignment.find({"project_id": {"$in": project_ids}}).to_list() if project_ids else []
    user_ids = [a.user_id for a in assignments]
    users = await User.find({"id": {"$in": user_ids}, "is_deleted": False}, fetch_links=True).to_list() if user_ids else []
    user_map = {u.id: u for u in users}

    by_project: dict[Any, list[dict[str, Any]]] = {}
    for a in assignments:
        u = user_map.get(a.user_id)
        if not u:
            continue
        by_project.setdefault(a.project_id, []).append({
            "id": str(u.id),
            "full_name": u.full_name,
            "employee_code": u.employee_code,
            "department": u.department,
            "designation": u.designation,
        })

    return [
        {
            "project_id": str(p.id),
            "project_code": p.project_code,
            "project_name": p.name,
            "expected_completion_date": p.expected_completion_date,
            "status": p.status,
            "users": by_project.get(p.id, []),
        }
        for p in projects
    ]


@router.put("/{id}/assignments")
async def replace_project_assignments(
    *,
    id: UUID,
    payload: ProjectAssignmentsUpdate,
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    # Try to find project by id
    from uuid import UUID as _UUID
    project = await Project.find_one({"_id": id, "is_deleted": False})
    if not project:
        # fallback: search all and match
        all_projects = await Project.find({"is_deleted": False}).to_list()
        project = next((p for p in all_projects if str(p.id) == str(id)), None)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found (id={id})")

    # If user_ids provided, validate them; skip if empty (clearing all)
    if payload.user_ids:
        users = await User.find({"is_deleted": False}, fetch_links=False).to_list()
        found_ids = {str(u.id) for u in users}
        missing = [str(uid) for uid in payload.user_ids if str(uid) not in found_ids]
        if missing:
            raise HTTPException(status_code=404, detail=f"Users not found: {', '.join(missing)}")

    project_uuid = project.id
    existing = await ProjectAssignment.find(ProjectAssignment.project_id == project_uuid).to_list()
    existing_user_ids = {str(a.user_id) for a in existing}
    target_user_ids = {str(uid) for uid in payload.user_ids}

    # remove users not selected anymore
    for a in existing:
        if str(a.user_id) not in target_user_ids:
            await a.delete()

    # add new selections
    for uid in target_user_ids:
        if uid not in existing_user_ids:
            from uuid import UUID as _UUID2
            await ProjectAssignment(project_id=project_uuid, user_id=_UUID2(uid)).insert()

    return {"msg": "Assignments updated", "project_id": str(project_uuid), "user_count": len(target_user_ids)}


@router.put("/assignments/user/{user_id}")
async def replace_user_project_assignments(
    *,
    user_id: UUID,
    payload: UserProjectAssignmentsUpdate,
    current_user: User = Depends(deps.get_current_active_admin),
) -> Any:
    # Validate user exists
    user = await User.find_one(User.id == user_id, User.is_deleted == False)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Validate all projects exist
    if payload.project_ids:
        projects = await Project.find(In(Project.id, payload.project_ids), Project.is_deleted == False).to_list()
        found_ids = {str(p.id) for p in projects}
        missing = [str(pid) for pid in payload.project_ids if str(pid) not in found_ids]
        if missing:
            raise HTTPException(status_code=404, detail=f"Projects not found: {', '.join(missing)}")

    # Get current assignments
    existing = await ProjectAssignment.find(ProjectAssignment.user_id == user_id).to_list()
    existing_project_ids = {str(a.project_id) for a in existing}
    target_project_ids = {str(pid) for pid in payload.project_ids}

    # Remove unselected projects
    for a in existing:
        if str(a.project_id) not in target_project_ids:
            await a.delete()

    # Add new selections
    for pid in target_project_ids:
        if pid not in existing_project_ids:
            from uuid import UUID as _UUID2
            await ProjectAssignment(project_id=_UUID2(pid), user_id=user_id).insert()

    return {"msg": "User project assignments updated", "user_id": str(user_id), "project_count": len(target_project_ids)}

