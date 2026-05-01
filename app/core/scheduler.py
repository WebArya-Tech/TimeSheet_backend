from datetime import date, datetime
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
except Exception:  # pragma: no cover - allow backend to run without scheduler in local dev
    AsyncIOScheduler = None
from app.models.user import User
from app.models.timesheet import TimesheetHeader
from app.models.notification import Notification
from beanie.operators import In
from app.models.leave import Leave
from app.models.holiday import Holiday
from app.models.timesheet import TimesheetEntry
from datetime import timedelta

async def send_daily_timesheet_reminders():
    """
    Send reminders to users who haven't filled their timesheet for the day.
    Runs at 10 AM and 5 PM.
    """
    today = date.today()
    users = await User.find(User.is_deleted == False).to_list()
    user_ids = [user.id for user in users]

    # Find users who already have entries for today
    entries = await TimesheetEntry.find(
        TimesheetEntry.date == today.isoformat(),
        TimesheetEntry.is_deleted == False,
    ).to_list()
    users_with_entries = {e.timesheet_id for e in entries}

    users_to_notify = []
    for user in users:
        # Skip deleted users
        if user.is_deleted:
            continue

        # Skip users on approved leave covering today
        leave = await Leave.find_one({
            "user.$id": user.id,
            "status": "approved",
            "from_date": {"$lte": today.isoformat()},
            "to_date": {"$gte": today.isoformat()},
        })
        if leave:
            continue

        # Skip if today is a holiday
        hol = await Holiday.find_one(Holiday.holiday_date == today)
        if hol:
            continue

        # Skip if user has an entry for today (by checking headers -> entries)
        # Find header for user covering this week
        header = await TimesheetHeader.find_one(
            TimesheetHeader.user_id == user.id,
            TimesheetHeader.week_start <= today,
            TimesheetHeader.week_end >= today,
        )
        has_entry = False
        if header:
            day_entries = await TimesheetEntry.find(
                TimesheetEntry.timesheet_id == header.id,
                TimesheetEntry.date == today.isoformat(),
                TimesheetEntry.is_deleted == False,
            ).to_list()
            if day_entries:
                has_entry = True

        if has_entry:
            continue

        users_to_notify.append(user)

    # Avoid sending duplicate reminders within the same day
    for user in users_to_notify:
        # Check if a similar notification was already sent today
        yesterday = today - timedelta(days=1)
        existing = await Notification.find({
            "user.$id": user.id,
            "title": "Daily Timesheet Reminder",
            "created_at": {"$gte": yesterday.isoformat()},
        }).to_list()
        if existing:
            continue

        await Notification(
            user=user,
            type="warning",
            title="Daily Timesheet Reminder",
            message=f"Please fill your timesheet for {today.strftime('%A, %d %B %Y')}.",
            link=f"/daily-entry?date={today.isoformat()}",
        ).insert()

async def send_weekly_submission_reminders():
    """
    Send reminders to all users, admins, and super admins to submit their weekly timesheet.
    Runs every Friday at 5 PM.
    """
    # Improved logic:
    # - Run daily at 17:00. When today is Friday and user is working, send reminder.
    # - If today is the day before Friday and Friday is a holiday or user on leave, send reminder today.
    today = date.today()
    # calculate this week's Friday
    start_of_week = today - timedelta(days=today.weekday())
    friday = start_of_week + timedelta(days=4)

    users = await User.find(User.is_deleted == False).to_list()

    for user in users:
        try:
            # Skip deleted users
            if user.is_deleted:
                continue

            # If today is Friday and user is working (not on leave and not global holiday)
            send_today = False
            # Check if this week's Friday is a holiday
            friday_hol = await Holiday.find_one(Holiday.holiday_date == friday)
            # Check if user is on leave for Friday
            user_on_friday_leave = await Leave.find_one({
                "user.$id": user.id,
                "status": "approved",
                "from_date": {"$lte": friday.isoformat()},
                "to_date": {"$gte": friday.isoformat()},
            })

            if today == friday:
                # If user not on leave and Friday not holiday, send reminder
                if not friday_hol and not user_on_friday_leave:
                    send_today = True
            elif today == friday - timedelta(days=1):
                # If tomorrow (Friday) is holiday or user on Friday leave, send today
                if friday_hol or user_on_friday_leave:
                    send_today = True

            if not send_today:
                continue

            # Check if user already submitted or has a timesheet entries for the week
            week_header = await TimesheetHeader.find_one(
                TimesheetHeader.user_id == user.id,
                TimesheetHeader.week_start <= friday,
                TimesheetHeader.week_end >= friday,
            )
            already_submitted = False
            if week_header and week_header.status in {"Submitted", "Approved"}:
                already_submitted = True

            if already_submitted:
                continue

            # Avoid duplicates: check recent similar notifications (48 hours)
            cutoff = (today - timedelta(days=2)).isoformat()
            existing = await Notification.find({
                "user.$id": user.id,
                "title": "Weekly Timesheet Submission Reminder",
                "created_at": {"$gte": cutoff},
            }).to_list()
            if existing:
                continue

            await Notification(
                user=user,
                type="info",
                title="Weekly Timesheet Submission Reminder",
                message="Please ensure your weekly timesheet is filled for the previous days and today (if applicable) and submit by the end of the day.",
                link="/weekly-submission",
            ).insert()
        except Exception:
            # don't let a single user error stop the loop
            logging.exception("Failed to send weekly reminder to user %s", getattr(user, "id", None))

def setup_scheduler():
    """
    Initializes and starts the APScheduler with the defined jobs.
    """
    if AsyncIOScheduler is None:
        # Scheduler package not installed; skip scheduling but don't crash app
        return None
    scheduler = AsyncIOScheduler()
    # Daily reminders at 10 and 17
    scheduler.add_job(send_daily_timesheet_reminders, 'cron', hour='10,17', minute=0)
    # Run weekly reminder logic daily at 17:00 — internal logic decides whether to send
    scheduler.add_job(send_weekly_submission_reminders, 'cron', hour=17, minute=0)
    scheduler.start()
    return scheduler