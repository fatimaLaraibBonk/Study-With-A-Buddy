# moderation.py automated reporting 
# Called from SWB.py inside report_user() immediately after the report is saved.
#   from moderation import evaluate_user
#   evaluate_user(db_connection, reported_user_id)
#
# The algorithm looks at:
# Total report count against the user
# Their average star rating  (lower = worse)
# Number of "Harassment" reports (instant-escalation trigger)
#
# Decision table
#   BANNED     : ≥ 10 reports  OR  ≥ 3 Harassment reports
#   SUSPENDED  : ≥ 5 reports   AND  rating < 2.5     → 7 days
#              : ≥ 3 reports   AND  rating < 2.0     → 3 days
#              : ≥ 2 Harassment reports               → 5 days
#   NOTHING    : everything else
#
# Suspension length is stored in `suspension_days` (INT) in the users table.
# A background worker (already present in SWB.py's _countdown_worker or a new
# one added here) decrements it daily and clears the suspended flag when it
# reaches 0.


import threading
import time


BAN_REPORT_THRESHOLD        = 10   
BAN_HARASSMENT_THRESHOLD    = 3  
SUSPEND_HEAVY_REPORTS       = 5    
SUSPEND_HEAVY_RATING        = 2.5
SUSPEND_HEAVY_DAYS          = 7
SUSPEND_LIGHT_REPORTS       = 3   
SUSPEND_LIGHT_RATING        = 2.0
SUSPEND_LIGHT_DAYS          = 3
SUSPEND_HARASSMENT_REPORTS  = 2    
SUSPEND_HARASSMENT_DAYS     = 5


def evaluate_user(db, reported_id: int) -> dict:

    cur = db.cursor(dictionary=True)
    #fetch required data
    cur.execute(
        "SELECT account_status, user_rating, rating_count FROM users WHERE user_id = %s",
        (reported_id,)
    )
    user = cur.fetchone()
    if not user:
        cur.close()
        return {"action": "none", "days": 0, "previous": None, "message": "User not found."}

    previous_status = user["account_status"]
    if previous_status == "banned":
        cur.close()
        return {"action": "none", "days": 0, "previous": previous_status,
                "message": "User is already banned."}

    rating = float(user["user_rating"] or 0.0)
    #count number of reports
    cur.execute(
        "SELECT COUNT(*) AS total FROM reports WHERE reported_id = %s",
        (reported_id,)
    )
    total_reports = cur.fetchone()["total"]
    cur.execute(
        "SELECT COUNT(*) AS cnt FROM reports WHERE reported_id = %s AND reason = 'Harassment'",
        (reported_id,)
    )
    harassment_reports = cur.fetchone()["cnt"]
    #decision logic-> via if else 
    action = "none"
    days   = 0
    if total_reports >= BAN_REPORT_THRESHOLD or harassment_reports >= BAN_HARASSMENT_THRESHOLD:
        action = "ban"
    elif (total_reports >= SUSPEND_HEAVY_REPORTS and rating < SUSPEND_HEAVY_RATING):
        action = "suspend"
        days   = SUSPEND_HEAVY_DAYS
    elif (total_reports >= SUSPEND_LIGHT_REPORTS and rating < SUSPEND_LIGHT_RATING):
        action = "suspend"
        days   = SUSPEND_LIGHT_DAYS
    elif harassment_reports >= SUSPEND_HARASSMENT_REPORTS:
        action = "suspend"
        days   = SUSPEND_HARASSMENT_DAYS
    #apply result on user 
    if action == "ban":
        cur.execute(
            "UPDATE users SET account_status = 'banned', suspension_days = 0 WHERE user_id = %s",
            (reported_id,)
        )
        #Delete all slots owned by this user
        cur.execute("DELETE FROM slots WHERE owner_id = %s", (reported_id,))
        _insert_notification(cur, reported_id,
            "Your account has been permanently banned due to repeated violations. "
            "Your active slots have been removed.",
            "general")
        message = f"User {reported_id} has been BANNED."

    elif action == "suspend":
        # If already suspended, extend rather than reset to a shorter period
        if previous_status == "suspended":
            cur.execute(
                "SELECT suspension_days FROM users WHERE user_id = %s",
                (reported_id,)
            )
            existing_days = cur.fetchone()["suspension_days"] or 0
            days = max(days, existing_days)  # never shorten an active suspension

        cur.execute(
            """UPDATE users
               SET account_status = 'suspended', suspension_days = %s
               WHERE user_id = %s""",
            (days, reported_id)
        )
        # Delete all slots owned by this user so they don't linger on the home page
        cur.execute("DELETE FROM slots WHERE owner_id = %s", (reported_id,))
        _insert_notification(cur, reported_id,
            f"Your account has been suspended for {days} day(s) due to reports from other users. "
            f"Your active slots have been removed.",
            "general")
        message = f"User {reported_id} SUSPENDED for {days} day(s)."

    else:
        message = f"User {reported_id}: no sanction applied (reports={total_reports}, rating={rating:.2f})."

    db.commit()
    cur.close()

    return {
        "action":   action,
        "days":     days,
        "previous": previous_status,
        "message":  message,
    }


def _insert_notification(cur, user_id: int, message: str, notif_type: str):
    cur.execute(
        "INSERT INTO notifications (user_id, message, notif_type) VALUES (%s, %s, %s)",
        (user_id, message, notif_type)
    )

def _suspension_decay_worker(get_db_fn):
    """
    Runs in a daemon thread.  Every 24 h it:
      1. Decrements suspension_days by 1 for all suspended users.
      2. Lifts the suspension (sets account_status = 'active') for anyone
         whose suspension_days has just reached 0.
    """ 
    #server snould be working whole hat period but doesnt 
    while True:
        time.sleep(86_400)          # 24 hours
        try:
            db  = get_db_fn()
            cur = db.cursor(dictionary=True)

            # Decrement
            cur.execute(
                "UPDATE users SET suspension_days = suspension_days - 1 "
                "WHERE account_status = 'suspended' AND suspension_days > 0"
            )

            # Lift expired suspensions
            cur.execute(
                "SELECT user_id FROM users "
                "WHERE account_status = 'suspended' AND suspension_days <= 0"
            )
            expired = cur.fetchall()
            for row in expired:
                cur.execute(
                    "UPDATE users SET account_status = 'active', suspension_days = 0 "
                    "WHERE user_id = %s",
                    (row["user_id"],)
                )
                _insert_notification(cur, row["user_id"],
                    "Your suspension has ended. Welcome back to StudyWithABuddy!",
                    "general")

            db.commit()
            cur.close()
            db.close()
        except Exception as e:
            print(f"[suspension_decay_worker] Error: {e}")


def start_suspension_worker(get_db_fn):
    """Call this once at app startup (after the Werkzeug guard)."""
    t = threading.Thread(target=_suspension_decay_worker, args=(get_db_fn,), daemon=True)
    t.start()
