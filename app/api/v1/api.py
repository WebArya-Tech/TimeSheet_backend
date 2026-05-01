from fastapi import APIRouter
from app.api.v1 import (
    auth,
    users,
    projects,
    categories,
    timesheets,
    approvals,
    reports,
    attendances,
    leaves,
    holidays,
    notifications,
    system,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(categories.router, prefix="/categories", tags=["categories"])
api_router.include_router(timesheets.router, prefix="/timesheets", tags=["timesheets"])
api_router.include_router(approvals.router, prefix="/approvals", tags=["approvals"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(attendances.router, prefix="/attendances", tags=["attendances"])
api_router.include_router(leaves.router, prefix="/leaves", tags=["leaves"])
api_router.include_router(holidays.router, prefix="/holidays", tags=["holidays"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(system.router, prefix="/system", tags=["system"])
