from pymongo import AsyncMongoClient
from beanie import init_beanie
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

# Global client
client = None

async def init_db():
    global client
    try:
        logger.info("Initializing MongoDB connection...")
        client = AsyncMongoClient(settings.DATABASE_URL, uuidRepresentation="standard", serverSelectionTimeoutMS=5000)
        
        # Needs to import all Beanie documents
        from app.models.role import Role
        from app.models.user import User
        from app.models.project import Project, ProjectAssignment
        from app.models.category import Category
        from app.models.timesheet import TimesheetHeader, TimesheetEntry
        from app.models.holiday import Holiday
        from app.models.audit_log import AuditLog
        from app.models.attendance import Attendance
        from app.models.leave import Leave
        from app.models.notification import Notification
        from app.models.system_setting import SystemSetting

        await init_beanie(
            database=client.timesheet_db,
            document_models=[
                Role,
                User,
                Project,
                ProjectAssignment,
                Category,
                TimesheetHeader,
                TimesheetEntry,
                Holiday,
                AuditLog,
                Attendance,
                Leave,
                Notification,
                SystemSetting,
            ]
        )
        # Test connection
        await client.admin.command('ping')
        logger.info("MongoDB and Beanie initialized successfully.")
    except Exception as e:
        logger.error(f"Critical Error: Could not connect to MongoDB. Ensure it is running at {settings.DATABASE_URL}")
        logger.error(f"Error details: {e}")
        raise e

async def close_db():
    global client
    if client:
        res = client.close()
        # Some drivers expose close() as a coroutine
        if hasattr(res, "__await__"):
            await res
        logger.info("MongoDB connection closed.")
