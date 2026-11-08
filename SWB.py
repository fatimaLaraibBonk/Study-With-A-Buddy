#flask backend
import os
import re
import smtplib
import threading
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText #email verification
from functools import wraps
import mysql.connector #to connect with database 
from flask import (Flask, flash, redirect, render_template, request,
                   session, url_for)
import bcrypt
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
import random
from moderation import evaluate_user, start_suspension_worker
from animations import register_animations, push_anim_event

def get_db():
    #connection to DB 
    return mysql.connector.connect(
        host=os.environ.get("DB_HOST", ""),
        user=os.environ.get("DB_USER", ""),
        password=os.environ.get("DB_PASS", ""),
        database="studyWithABuddyDB",
    )

#profile titles 
def get_title(rating, sessions):
    if sessions >= 50 and rating >= 4.8:
        return {'label': '🌟 Legendary Buddy',   'bg': '#FFD700', 'border': '#b8860b'}
    if sessions >= 30 and rating >= 4.5:
        return {'label': '🏆 Elite Scholar',      'bg': '#E69BFF', 'border': '#7B2D8B'}
    if sessions >= 20 and rating >= 4.2:
        return {'label': '🔥 Study Machine',       'bg': '#FFB366', 'border': '#c97a2a'}
    if sessions >= 10 and rating >= 3.8:
        return {'label': '⭐ Professional Buddy', 'bg': '#FFFFD1', 'border': '#999900'}
    if sessions >= 5:
        return {'label': '📖 Rising Scholar',     'bg': '#d4edda', 'border': '#155724'}
    return     {'label': '🌱 Newcomer',           'bg': '#f0f0f0', 'border': '#aaa'}
    
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "")

#gmail credentials
#gotten by enabling 2 factor auth 
MAIL_SERVER   =os.environ.get("MAIL_SERVER",   "smtp.gmail.com")
MAIL_PORT     =int(os.environ.get("MAIL_PORT",  "587"))
MAIL_USERNAME =os.environ.get("MAIL_USERNAME",  "")
MAIL_PASSWORD =os.environ.get("MAIL_PASSWORD",  "")
MAIL_FROM     =os.environ.get("MAIL_FROM",      "StudyWithABuddy")
UNI_EMAIL     =os.environ.get("UNI_EMAIL",      "")

serializer = URLSafeTimedSerializer(app.secret_key)

# Register animation injection hook (Feature 5)
register_animations(app, get_db)

#avatar map 
AVATARS = {
    0: "🧑", 1: "📚", 2: "🎓", 3: "🦉", 4: "🐱",
    5: "🐶", 6: "🐼", 7: "🦊", 8: "🌟", 9: "🎸",
}

#database connection helper
#this function will be used repetitively
#before running something=> check if user id exists in slots 
#session stores user's browser data 

def login_required(f):
    @wraps(f) #make wrapper function behave like original 
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        # Check if account has been suspended or banned since last login
        db = get_db()
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT account_status, suspension_days FROM users WHERE user_id = %s",
                    (session["user_id"],))
        user = cur.fetchone()
        cur.close(); db.close()
        if user:
            status = user.get("account_status", "active")
            if status == "banned":
                session.clear()
                flash("Your account has been permanently banned.", "error")
                return redirect(url_for("login"))
            if status == "suspended":
                days = user.get("suspension_days", 0)
                session.clear()
                flash(f"Your account has been suspended for {days} day(s) due to reports from other users.", "error")
                return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated
#@login required-> home=login_required(home)

def _countdown_worker():
    #daemon thread
    #ticks every 60 seconds
    #helps manage session time 
    #needs website ot automatically reload-> not done yet 
    while True:
        time.sleep(60)
        try:
            db = get_db()
            cur = db.cursor(dictionary=True)
            #reduce time 
            cur.execute("""
                SELECT s.slot_id, s.owner_id, s.subject_name, u.user_name,
                       s.remaining_time AS original_time
                FROM slots s
                JOIN users u ON u.user_id = s.owner_id
                WHERE s.remaining_time <= 1
            """)
            expiring = cur.fetchall()

            #Decrement all active slots
            cur.execute("UPDATE slots SET remaining_time = remaining_time - 1 WHERE remaining_time > 0")

            #Delete slots that hit 0 and notify owners + buddies
            for slot in expiring:
                # Notify owner
                cur.execute("""
                    INSERT INTO notifications (user_id, message, notif_type)
                    VALUES (%s, %s, 'session_ended')
                """, (slot["owner_id"],
                      f"Your slot for '{slot['subject_name']}' has expired and was automatically closed."))

                # Queue 'ending' animation for the owner
                cur.execute("""
                    INSERT INTO anim_events (user_id, event_type)
                    VALUES (%s, 'ending')
                """, (slot["owner_id"],))

                # Queue 'ending' animation for all accepted buddies
                cur.execute("""
                    SELECT requester_id FROM slot_requests
                    WHERE slot_id = %s AND status = 'accepted'
                """, (slot["slot_id"],))
                for buddy_row in cur.fetchall():
                    cur.execute("""
                        INSERT INTO anim_events (user_id, event_type)
                        VALUES (%s, 'ending')
                    """, (buddy_row["requester_id"],))

                # Record the completed session and its participants
                cur.execute("""
                    INSERT INTO completed_sessions (slot_id, owner_id, subject_name, minutes_run)
                    VALUES (%s, %s, %s, %s)
                """, (slot["slot_id"], slot["owner_id"], slot["subject_name"], slot["original_time"]))
                completed_id = cur.lastrowid

                # Add owner as participant
                cur.execute("""
                    INSERT IGNORE INTO completed_session_participants (completed_session_id, user_id)
                    VALUES (%s, %s)
                """, (completed_id, slot["owner_id"]))

                # Add all accepted buddies as participants
                cur.execute("""
                    SELECT requester_id FROM slot_requests
                    WHERE slot_id = %s AND status = 'accepted'
                """, (slot["slot_id"],))
                for p in cur.fetchall():
                    cur.execute("""
                        INSERT IGNORE INTO completed_session_participants (completed_session_id, user_id)
                        VALUES (%s, %s)
                    """, (completed_id, p["requester_id"]))

                # Delete the slot (cascades to slot_topics, slot_requests)
                cur.execute("DELETE FROM slots WHERE slot_id = %s", (slot["slot_id"],))

            db.commit()
            cur.close()
            db.close()
        except Exception as e:
            print(f"[countdown_worker] Error: {e}")



if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    _t = threading.Thread(target=_countdown_worker, daemon=True)
    _t.start()
    start_suspension_worker(get_db)   # daily suspension-decay thread


#EMAIL  HELPERS 
def _send_email(to: str, subject: str, html_body: str):
    def _send():
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = MAIL_FROM
            msg["To"]      = to
            msg.attach(MIMEText(html_body, "html"))
            with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.login(MAIL_USERNAME, MAIL_PASSWORD)
                smtp.sendmail(MAIL_FROM, to, msg.as_string())
        except Exception as e:
            print(f"[send_email] Failed: {e}")
    threading.Thread(target=_send, daemon=True).start()


def send_verification_email(to_email: str, username: str, token: str):
    verify_url = url_for("verify_email", token=token, _external=True)
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;border:1px solid #ddd;border-radius:8px;overflow:hidden;">
      <div style="background:#E69BFF;padding:20px 30px;">
        <h2 style="margin:0;color:#333;">Study With A Buddy</h2>
      </div>
      <div style="padding:30px;">
        <p>Hi <strong>{username}</strong>,</p>
        <p>Thanks for signing up! Please verify your email address by clicking the button below.
           The link expires in <strong>2 hours</strong>.</p>
        <p style="text-align:center;margin:30px 0;">
          <a href="{verify_url}"
             style="background:#E69BFF;color:#333;padding:12px 28px;text-decoration:none;
                    font-weight:bold;border:1px solid #333;border-radius:4px;">
            Verify My Email
          </a>
        </p>
        <p style="font-size:0.82rem;color:#888;">If you didn't create an account, you can safely ignore this email.</p>
      </div>
    </div>
    """
    _send_email(to_email, "Verify your StudyWithABuddy account", html)


#report 
def send_report_email(reporter_name: str, reporter_email: str,
                      reported_name: str, reported_email: str,
                      reason: str, to_university: bool,
                      moderation_action: str = "none", moderation_days: int = 0):
    """
    Sends a nicely-formatted HTML report email to fatimalaraib06@gmail.com.
    Both internal reports and university-escalated reports go to the same inbox;
    the subject line and scope label distinguish them.
    """
    dest = UNI_EMAIL if to_university else MAIL_USERNAME
    scope = "University Management" if to_university else "Platform Admins"
    subject = f"[SWB Report {'→ University' if to_university else ''}] {reporter_name} reported {reported_name}"

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:620px;margin:auto;
                border:1px solid #ddd;border-radius:8px;overflow:hidden;">
      <div style="background:#FF8080;padding:20px 30px;">
        <h2 style="margin:0;color:#fff;">⚠️ User Report — StudyWithABuddy</h2>
        <p style="margin:4px 0 0;color:#fff;font-size:0.9rem;">Submitted to: {scope}</p>
      </div>
      <div style="padding:30px;">
        <table style="width:100%;border-collapse:collapse;font-size:0.95rem;">
          <tr>
            <td style="padding:8px 12px;background:#fff0f0;font-weight:bold;border:1px solid #f5c6cb;width:40%;">
              Reported by
            </td>
            <td style="padding:8px 12px;border:1px solid #f5c6cb;">
              {reporter_name} &lt;{reporter_email}&gt;
            </td>
          </tr>
          <tr>
            <td style="padding:8px 12px;background:#fff0f0;font-weight:bold;border:1px solid #f5c6cb;">
              Reported user
            </td>
            <td style="padding:8px 12px;border:1px solid #f5c6cb;">
              {reported_name} &lt;{reported_email}&gt;
            </td>
          </tr>
          <tr>
            <td style="padding:8px 12px;background:#fff0f0;font-weight:bold;border:1px solid #f5c6cb;">
              Reason
            </td>
            <td style="padding:8px 12px;border:1px solid #f5c6cb;font-weight:bold;color:#c0392b;">
              {reason}
            </td>
          </tr>
          <tr>
            <td style="padding:8px 12px;background:#fff0f0;font-weight:bold;border:1px solid #f5c6cb;">
              Escalated to university
            </td>
            <td style="padding:8px 12px;border:1px solid #f5c6cb;">
              {'<span style="color:#c0392b;font-weight:bold;">YES</span>' if to_university else 'No'}
            </td>
          </tr>
          <tr>
            <td style="padding:8px 12px;background:#fff0f0;font-weight:bold;border:1px solid #f5c6cb;">
              Automated action taken
            </td>
            <td style="padding:8px 12px;border:1px solid #f5c6cb;font-weight:bold;">
              {
                '<span style="color:#c0392b;">BANNED</span>' if moderation_action == 'ban'
                else f'<span style="color:#e67e22;">SUSPENDED {moderation_days} day(s)</span>' if moderation_action == 'suspend'
                else '<span style="color:#888;">None</span>'
              }
            </td>
          </tr>
        </table>
        <p style="margin-top:24px;font-size:0.82rem;color:#888;">
          This is an automated report from the StudyWithABuddy platform.
          The moderation engine has already evaluated this user and applied the action shown above.
        </p>
      </div>
    </div>
    """
    _send_email(dest, subject, html)


#get number of un-read notifications 
def get_notif_count(user_id: int) -> int:
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM notifications WHERE user_id=%s AND is_read=FALSE", (user_id,))
    count = cur.fetchone()[0]
    # Also count incoming pending requests for the user's slot
    cur.execute("""
        SELECT COUNT(*) FROM slot_requests sr
        JOIN slots s ON s.slot_id = sr.slot_id
        WHERE s.owner_id = %s AND sr.status = 'pending'
    """, (user_id,))
    count += cur.fetchone()[0]
    cur.close(); db.close()
    return count


def get_user_slot(user_id: int):
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM slots WHERE owner_id = %s LIMIT 1", (user_id,))
    slot = cur.fetchone()
    if slot:
        cur.execute("SELECT topic FROM slot_topics WHERE slot_id = %s", (slot["slot_id"],))
        slot["topics"] = [r["topic"] for r in cur.fetchall()]
    cur.close(); db.close()
    return slot


def get_accepted_slot(user_id: int):
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT s.*, u.user_name AS owner_name, u.avatar_id AS owner_avatar_id,
               u.user_rating, u.rating_count
        FROM slot_requests sr
        JOIN slots s ON s.slot_id = sr.slot_id
        JOIN users u ON u.user_id = s.owner_id
        WHERE sr.requester_id = %s AND sr.status = 'accepted'
        LIMIT 1
    """, (user_id,))
    slot = cur.fetchone()
    if slot:
        slot["owner_avatar"] = AVATARS.get(slot["owner_avatar_id"], "🧑")

    cur.close(); db.close()
    return slot


@app.route("/", methods=["GET"])
def index():
    if "user_id" in session:
        return redirect(url_for("home"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT * FROM users WHERE user_email = %s", (email,))
        user = cur.fetchone()
        cur.close(); db.close()
        if not user or not bcrypt.checkpw(password.encode('utf-8'), user["user_password"].encode('utf-8')):
            flash("Invalid email or password.", "error")
            return redirect(url_for("login"))
        if not user["is_verified"]:
            flash("Please verify your email first.", "error")
            return redirect(url_for("login"))
        # ── Moderation checks ──────────────────────────────────────────
        status = user.get("account_status", "active")
        if status == "banned":
            return render_template("login.html", account_banned=True)
        if status == "suspended":
            days_left = user.get("suspension_days", 0)
            return render_template("login.html", account_suspended=True, suspension_days=days_left)
        # ──────────────────────────────────────────────────────────────
        session["user_id"]   = user["user_id"]
        session["user_name"] = user["user_name"]
        flash("Login successful!", "success")
        return render_template("login.html", login_success=True)
    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "GET":
        return render_template("signup.html", show_verify=False)
    name     = request.form.get("name", "").strip()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    email    = request.form.get("email", "").strip()
    if not all([name, username, password, email]):
        flash("All fields are required.", "error")
        return render_template("signup.html", show_verify=False)

    if len(password) < 8:
        flash("Password must be at least 8 characters.", "error")
        return render_template("signup.html", show_verify=False)

    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT user_id FROM users WHERE user_email=%s OR user_name=%s", (email, username))
    if cur.fetchone():
        cur.close(); db.close()
        flash("Username or email already taken.", "error")
        return render_template("signup.html", show_verify=False)
    cur.close(); db.close()

    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    code   = str(random.randint(100000, 999999))

    session["pending_name"]     = name
    session["pending_username"] = username
    session["pending_email"]    = email
    session["pending_password"] = hashed
    session["pending_code"]     = code

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;
                border:1px solid #ddd;border-radius:8px;overflow:hidden;">
      <div style="background:#E69BFF;padding:20px 30px;">
        <h2 style="margin:0;color:#333;">Study With A Buddy</h2>
      </div>
      <div style="padding:30px;">
        <p>Hi <strong>{username}</strong>,</p>
        <p>Your verification code is:</p>
        <h1 style="letter-spacing:8px;color:#333;margin:20px 0;">{code}</h1>
        <p style="color:#888;font-size:0.85rem;">Enter this code to activate your account.</p>
      </div>
    </div>
    """
    try:
        _send_email(email, "StudyWithABuddy — Verify your email", html)
    except Exception as e:
        print("EMAIL ERROR:", e)
        flash("Could not send email. Check your address.", "error")
        return render_template("signup.html", show_verify=False)

    return render_template("signup.html", show_verify=True)


@app.route("/verify", methods=["POST"])
def verify():
    if "pending_email" not in session:
        return redirect(url_for("signup"))
    code = request.form.get("code", "").strip()
    if code != session.get("pending_code"):
        flash("Invalid code. Try again.", "error")
        return render_template("signup.html", show_verify=True)

    db = get_db()
    cur = db.cursor()
    try:
        cur.execute("""
            INSERT INTO users (user_name, user_password, user_email, is_verified)
            VALUES (%s, %s, %s, TRUE)
        """, (session["pending_username"], session["pending_password"], session["pending_email"]))
        db.commit()
    except mysql.connector.IntegrityError:
        cur.close(); db.close()
        flash("Username or email already taken.", "error")
        return render_template("signup.html", show_verify=False)
    cur.close(); db.close()

    for key in ["pending_name", "pending_username", "pending_email", "pending_password", "pending_code"]:
        session.pop(key, None)

    flash("Account created! You can now log in.", "success")
    return redirect(url_for("login"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


#home page 
#display all slots 
@app.route("/home")
@login_required
def home():
    user_id = session["user_id"]
    db = get_db()
    cur = db.cursor(dictionary=True)

    # All slots except user's own
    cur.execute("""
        SELECT s.*, u.user_name AS owner_name, u.user_rating, u.rating_count,
               u.avatar_id
        FROM slots s
        JOIN users u ON u.user_id = s.owner_id
        ORDER BY s.created_at DESC
    """)
    raw_slots = cur.fetchall()

    slots = []
    for slot in raw_slots:
        cur.execute("SELECT topic FROM slot_topics WHERE slot_id = %s", (slot["slot_id"],))
        slot["topics"]  = [r["topic"] for r in cur.fetchall()]
        slot["avatar"]  = AVATARS.get(slot["avatar_id"], "🧑")
        slot["is_mine"] = (slot["owner_id"] == user_id)
        # Check if current user has a request for this slot
        cur.execute("""
            SELECT status FROM slot_requests
            WHERE slot_id = %s AND requester_id = %s
        """, (slot["slot_id"], user_id))
        req = cur.fetchone()
        slot["req_status"] = req["status"] if req else None
        slots.append(slot)

    my_slot   = get_user_slot(user_id)
    has_slot  = my_slot is not None

    # User is "in_session" if they have an accepted request on someone else's slot
    in_session = get_accepted_slot(user_id) is not None

    cur.close(); db.close()

    return render_template("home.html",
        slots=slots,
        my_slot=my_slot,
        has_slot=has_slot,
        in_session=in_session,
        notif_count=get_notif_count(user_id),
        user_id=user_id,
    )


#slot handling 
@app.route("/post_slot", methods=["POST"])
@login_required
def post_slot():
    user_id  = session["user_id"]
    subject  = request.form.get("subject_name", "").strip()
    gen_loc  = request.form.get("general_location", "").strip()
    prec_loc = request.form.get("precise_location", "").strip()
    topics_s = request.form.get("topics", "")
    try:
        rem_time = int(request.form.get("remaining_time", 60))
    except ValueError:
        rem_time = 60
    slot_type = request.form.get("slot_type", "buddy")

    if not all([subject, gen_loc, prec_loc]):
        flash("Please fill in all fields.", "error")
        return redirect(url_for("home"))

    db = get_db()
    cur = db.cursor()
    cur.execute("""
        INSERT INTO slots (owner_id, subject_name, general_location, precise_location,
                           remaining_time, slot_type)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (user_id, subject, gen_loc, prec_loc, rem_time, slot_type))
    slot_id = cur.lastrowid

    topics = [t.strip() for t in topics_s.split(",") if t.strip()]
    for topic in topics:
        cur.execute("INSERT INTO slot_topics (slot_id, topic) VALUES (%s, %s)", (slot_id, topic))

    db.commit()
    cur.close(); db.close()
    push_anim_event(session, 'starting')
    flash("Slot posted!", "success")
    return redirect(url_for("home"))


@app.route("/delete_slot/<int:slot_id>", methods=["POST"])
@login_required
def delete_slot(slot_id):
    user_id = session["user_id"]
    db = get_db()
    cur = db.cursor(dictionary=True)

    # Fetch slot details before deleting to record the completed session
    cur.execute("SELECT slot_id, subject_name, remaining_time FROM slots WHERE slot_id = %s AND owner_id = %s", (slot_id, user_id))
    slot = cur.fetchone()

    if slot:
        cur.execute("INSERT INTO completed_sessions (slot_id, owner_id, subject_name, minutes_run) VALUES (%s, %s, %s, %s)",
                    (slot["slot_id"], user_id, slot["subject_name"], slot["remaining_time"]))
        completed_id = cur.lastrowid

        cur.execute("INSERT IGNORE INTO completed_session_participants (completed_session_id, user_id) VALUES (%s, %s)",
                    (completed_id, user_id))

        cur.execute("SELECT requester_id FROM slot_requests WHERE slot_id = %s AND status = 'accepted'", (slot_id,))
        for p in cur.fetchall():
            cur.execute("INSERT IGNORE INTO completed_session_participants (completed_session_id, user_id) VALUES (%s, %s)",
                        (completed_id, p["requester_id"]))

        cur.execute("DELETE FROM slots WHERE slot_id = %s AND owner_id = %s", (slot_id, user_id))

    db.commit()
    cur.close(); db.close()
    redirect_to = request.form.get("redirect_to", "home")
    return redirect(url_for(redirect_to if redirect_to in ("home", "session_page") else "home"))


@app.route("/request_slot/<int:slot_id>", methods=["POST"])
@login_required
def request_slot(slot_id):
    user_id = session["user_id"]
    db = get_db()
    cur = db.cursor(dictionary=True)
    # Fetch slot owner
    cur.execute("SELECT owner_id FROM slots WHERE slot_id = %s", (slot_id,))
    slot = cur.fetchone()
    if not slot:
        flash("Slot not found.", "error")
        cur.close(); db.close()
        return redirect(url_for("home"))

    try:
        cur.execute("""
            INSERT INTO slot_requests (slot_id, requester_id) VALUES (%s, %s)
        """, (slot_id, user_id))
        # Notify owner
        cur.execute("SELECT user_name FROM users WHERE user_id = %s", (user_id,))
        uname = cur.fetchone()["user_name"]
        cur.execute("""
            INSERT INTO notifications (user_id, message, notif_type)
            VALUES (%s, %s, 'general')
        """, (slot["owner_id"], f"{uname} wants to join your slot!"))
        db.commit()
    except mysql.connector.IntegrityError:
        flash("You already requested this slot.", "error")

    cur.close(); db.close()
    return redirect(url_for("home"))


#leave someone's slot
@app.route("/leave_slot", methods=["POST"])
@login_required
def leave_slot():
    user_id = session["user_id"]
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT sr.request_id, s.subject_name, s.owner_id
        FROM slot_requests sr
        JOIN slots s ON s.slot_id = sr.slot_id
        WHERE sr.requester_id = %s AND sr.status = 'accepted'
        LIMIT 1
    """, (user_id,))
    req = cur.fetchone()
    if req:
        cur.execute("DELETE FROM slot_requests WHERE request_id = %s", (req["request_id"],))
        cur.execute("""
            INSERT INTO notifications (user_id, message, notif_type)
            VALUES (%s, %s, 'general')
        """, (req["owner_id"],
              f"{session['user_name']} has left your '{req['subject_name']}' slot."))
        db.commit()
    cur.close(); db.close()
    return redirect(url_for("session_page"))



#notifications page 
@app.route("/notifications")
@login_required
def notifications():
    user_id = session["user_id"]
    db = get_db()
    cur = db.cursor(dictionary=True)

    # Mark system notifications read
    cur.execute("""
        UPDATE notifications SET is_read = TRUE WHERE user_id = %s
    """, (user_id,))

    # Incoming requests for user's slot
    cur.execute("""
        SELECT sr.request_id, sr.requester_id,
               u.user_name AS name, u.user_rating AS rating,
               u.rating_count, u.avatar_id,
               s.subject_name AS subject
        FROM slot_requests sr
        JOIN slots s ON s.slot_id = sr.slot_id
        JOIN users u ON u.user_id = sr.requester_id
        WHERE s.owner_id = %s AND sr.status = 'pending'
        ORDER BY sr.requested_at DESC
    """, (user_id,))
    incoming_raw = cur.fetchall()

    incoming = []
    requester_map = {}
    for r in incoming_raw:
        cur.execute("SELECT topic FROM slot_topics WHERE slot_id = (SELECT slot_id FROM slot_requests WHERE request_id = %s)", (r["request_id"],))
        r["topics"] = ", ".join(x["topic"] for x in cur.fetchall())
        r["avatar"] = AVATARS.get(r["avatar_id"], "🧑")
        requester_map[r["request_id"]] = r["requester_id"]
        incoming.append(r)

    # System notifications
    cur.execute("""
        SELECT * FROM notifications WHERE user_id = %s ORDER BY created_at DESC LIMIT 50
    """, (user_id,))
    system_notifs = cur.fetchall()

    db.commit()
    cur.close(); db.close()

    return render_template("notifications.html",
        incoming=incoming,
        system_notifs=system_notifs,
        requester_map=requester_map,
        notif_count=0,   # just cleared them
    )


@app.route("/clear_notifications", methods=["POST"])
@login_required
def clear_notifications():
    user_id = session["user_id"]
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM notifications WHERE user_id = %s", (user_id,))
    db.commit()
    cur.close(); db.close()
    flash("All notifications cleared.", "success")
    return redirect(url_for("notifications"))


@app.route("/handle_request/<int:request_id>", methods=["POST"])
@login_required
def handle_request(request_id):
    user_id = session["user_id"]
    action  = request.form.get("action")
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("""
        SELECT sr.*, s.owner_id, s.subject_name
        FROM slot_requests sr
        JOIN slots s ON s.slot_id = sr.slot_id
        WHERE sr.request_id = %s
    """, (request_id,))
    req = cur.fetchone()
    if not req or req["owner_id"] != user_id:
        flash("Not authorised.", "error")
        cur.close(); db.close()
        return redirect(url_for("notifications"))
    #introduce new feature to clear up notifications
    if action == "accept":
        cur.execute("UPDATE slot_requests SET status='accepted' WHERE request_id=%s", (request_id,))
        cur.execute("""
            INSERT INTO notifications (user_id, message, notif_type)
            VALUES (%s, %s, 'request_accepted')
        """, (req["requester_id"],
              f"Your request to join '{req['subject_name']}' was ACCEPTED! Head to Your Session."))
        # Queue animation events: 'accepted' for the requester (DB), 'starting' for the owner
        cur.execute("""
            INSERT INTO anim_events (user_id, event_type) VALUES (%s, 'accepted')
        """, (req["requester_id"],))
        flash("Request accepted.", "success")

    elif action == "decline":
        cur.execute("UPDATE slot_requests SET status='rejected' WHERE request_id=%s", (request_id,))
        cur.execute("""
            INSERT INTO notifications (user_id, message, notif_type)
            VALUES (%s, %s, 'request_rejected')
        """, (req["requester_id"],
              f"Your request to join '{req['subject_name']}' was declined."))
        flash("Request declined.", "success")

    db.commit()
    cur.close(); db.close()
    return redirect(url_for("notifications"))


#session page 
@app.route("/session")
@login_required
def session_page():
    user_id = session["user_id"]
    db = get_db()
    cur = db.cursor(dictionary=True)
    my_slot        = get_user_slot(user_id)
    has_slot       = my_slot is not None
    accepted_buddies = []
    if has_slot and my_slot:
        cur.execute("""
            SELECT u.user_id, u.user_name AS name, u.user_rating AS rating,
                   u.rating_count, u.avatar_id,
                   EXISTS(SELECT 1 FROM friends
                          WHERE (user_id_1=LEAST(%s,u.user_id) AND user_id_2=GREATEST(%s,u.user_id))
                   ) AS is_friend
            FROM slot_requests sr
            JOIN users u ON u.user_id = sr.requester_id
            WHERE sr.slot_id = %s AND sr.status = 'accepted'
        """, (user_id, user_id, my_slot["slot_id"]))
        for b in cur.fetchall():
            b["avatar"] = AVATARS.get(b["avatar_id"], "🧑")
            accepted_buddies.append(b)

   #feature user joined SOMEONE ELSES SLOT 
    joined_slot = None
    cur.execute("""
        SELECT s.slot_id, s.subject_name, s.general_location,
               s.precise_location,
               s.remaining_time, s.slot_type,
               u.user_id  AS owner_id,
               u.user_name AS owner_name,
               u.avatar_id AS owner_avatar_id,
               u.user_rating, u.rating_count
        FROM slot_requests sr
        JOIN slots s ON s.slot_id = sr.slot_id
        JOIN users u ON u.user_id = s.owner_id
        WHERE sr.requester_id = %s AND sr.status = 'accepted'
        LIMIT 1
    """, (user_id,))
    joined_slot = cur.fetchone()
    if joined_slot:
        joined_slot["owner_avatar"] = AVATARS.get(joined_slot["owner_avatar_id"], "🧑")
        cur.execute("SELECT topic FROM slot_topics WHERE slot_id = %s", (joined_slot["slot_id"],))
        joined_slot["topics"] = [r["topic"] for r in cur.fetchall()]

    cur.close(); db.close()

    in_session = joined_slot is not None
    friend_ids = set()
    db2 = get_db()
    cur2 = db2.cursor()
    cur2.execute("""
        SELECT CASE WHEN user_id_1=%s THEN user_id_2 ELSE user_id_1 END
        FROM friends WHERE user_id_1=%s OR user_id_2=%s
    """, (user_id, user_id, user_id))
    friend_ids = {r[0] for r in cur2.fetchall()}
    cur2.close(); db2.close()

    return render_template("session.html",
        has_slot=has_slot,
        my_slot=my_slot,
        accepted_buddies=accepted_buddies,
        joined_slot=joined_slot,
        in_session=in_session,
        friend_ids=friend_ids,
        notif_count=get_notif_count(user_id),
    )


#report user-> not completed 
#needs automated banning
#needs proper direction to universirt managment
@app.route("/report_user/<int:reported_id>", methods=["POST"])
@login_required
def report_user(reported_id):
    reporter_id    = session["user_id"]
    reason         = request.form.get("reason", "Other")
    to_uni_str     = request.form.get("to_university", "false")
    to_university  = to_uni_str.lower() == "true"
    redirect_to    = request.form.get("redirect_to", "home")

    valid_reasons = {"Harassment", "No Show", "Spammer", "Other"}
    if reason not in valid_reasons:
        reason = "Other"

    db = get_db()
    cur = db.cursor(dictionary=True)

    # Fetch reporter info
    cur.execute("SELECT user_name, user_email FROM users WHERE user_id = %s", (reporter_id,))
    reporter = cur.fetchone()

    # Fetch reported info
    cur.execute("SELECT user_name, user_email FROM users WHERE user_id = %s", (reported_id,))
    reported = cur.fetchone()

    if not reported:
        flash("User not found.", "error")
        cur.close(); db.close()
        return redirect(url_for("home"))

    # Save to DB
    try:
        cur.execute("""
            INSERT INTO reports (reporter_id, reported_id, reason, to_university)
            VALUES (%s, %s, %s, %s)
        """, (reporter_id, reported_id, reason, to_university))
        db.commit()
    except Exception:
        pass   # duplicate or other; still send email

    # Close cursor before moderation so the same db connection isn't double-used
    cur.close()

    # ── Run moderation algorithm ───────────────────────────────────────────
    moderation_result = evaluate_user(db, reported_id)
    print(f"[moderation] {moderation_result['message']}")

    db.close()

    # ── Send report email ──────────────────────────────────────────────────
    send_report_email(
        reporter_name      = reporter["user_name"],
        reporter_email     = reporter["user_email"],
        reported_name      = reported["user_name"],
        reported_email     = reported["user_email"],
        reason             = reason,
        to_university      = to_university,
        moderation_action  = moderation_result.get("action", "none"),
        moderation_days    = moderation_result.get("days", 0),
    )

    # ── Flash outcome to reporter ──────────────────────────────────────────
    if to_university:
        flash("Report submitted and forwarded to the university.", "success")
    else:
        flash("Report submitted.", "success")

    # Notify reporter if the reported user was actioned (optional transparency)
    action = moderation_result.get("action", "none")
    if action == "ban":
        flash("The reported user has been permanently banned.", "success")
    elif action == "suspend":
        days = moderation_result.get("days", 0)
        flash(f"The reported user has been suspended for {days} day(s).", "success")

    return redirect(url_for(redirect_to if redirect_to in ("home", "session_page", "notifications") else "home"))


#rating user 
@app.route("/rate_user/<int:rated_id>", methods=["POST"])
@login_required
def rate_user(rated_id):
    rater_id=session["user_id"]
    try:
        stars = int(request.form.get("stars", 0))
    except ValueError:
        stars = 0
    if stars < 1 or stars > 5:
        flash("Invalid rating.", "error")
        return redirect(url_for("session_page"))

    db=get_db()
    cur=db.cursor()
    try:
        cur.execute("""
            INSERT INTO user_ratings (rater_id, rated_id, rating) VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE rating = VALUES(rating)
        """, (rater_id, rated_id, stars))
        cur.execute("""
            UPDATE users SET
                user_rating  = (SELECT AVG(rating) FROM user_ratings WHERE rated_id = %s),
                rating_count = (SELECT COUNT(*)    FROM user_ratings WHERE rated_id = %s)
            WHERE user_id = %s
        """, (rated_id, rated_id, rated_id))
        db.commit()
        flash("Rating submitted!", "success")
    except Exception as e:
        flash("Could not submit rating.", "error")
        print(e)
    cur.close(); db.close()
    return redirect(url_for("session_page"))


#friend/unfriend Module 
@app.route("/toggle_friend/<int:other_id>", methods=["POST"])
@login_required
def toggle_friend(other_id):
    user_id=session["user_id"]
    u1, u2=min(user_id, other_id), max(user_id, other_id)
    db=get_db()
    cur=db.cursor()
    cur.execute("SELECT friendship_id FROM friends WHERE user_id_1=%s AND user_id_2=%s", (u1, u2))
    existing = cur.fetchone()
    if existing:
        cur.execute("DELETE FROM friends WHERE user_id_1=%s AND user_id_2=%s", (u1, u2))
        flash("Removed from study buddies.", "success")
    else:
        cur.execute("INSERT INTO friends (user_id_1, user_id_2) VALUES (%s, %s)", (u1, u2))
        flash("Added as study buddy!", "success")
    db.commit()
    cur.close(); db.close()
    return redirect(url_for("session_page"))

#profile 
@app.route("/profile")
@login_required
def profile():
    user_id = session["user_id"]
    db = get_db()
    cur = db.cursor(dictionary=True)

    cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    user = cur.fetchone()

    #Friends with session-count
    cur.execute("""
        SELECT u.user_id, u.user_name AS name, u.user_rating AS rating,
               u.rating_count, u.avatar_id,
               0 AS sessions
        FROM friends f
        JOIN users u ON u.user_id = IF(f.user_id_1 = %s, f.user_id_2, f.user_id_1)
        WHERE f.user_id_1 = %s OR f.user_id_2 = %s
    """, (user_id, user_id, user_id))
    friends = cur.fetchall()

    # Stats from completed_sessions for accuracy
    cur.execute("""
        SELECT COUNT(DISTINCT cs.id) AS sessions_as_owner,
               COALESCE(SUM(cs.minutes_run), 0) AS minutes_as_owner
        FROM completed_sessions cs
        WHERE cs.owner_id = %s
    """, (user_id,))
    owner_stats = cur.fetchone()

    cur.execute("""
        SELECT COUNT(DISTINCT csp.completed_session_id) AS sessions_as_buddy,
               COALESCE(SUM(cs.minutes_run), 0) AS minutes_as_buddy
        FROM completed_session_participants csp
        JOIN completed_sessions cs ON cs.id = csp.completed_session_id
        WHERE csp.user_id = %s AND cs.owner_id != %s
    """, (user_id, user_id))
    buddy_stats = cur.fetchone()

    sessions_as_owner = owner_stats["sessions_as_owner"]
    sessions_as_buddy = buddy_stats["sessions_as_buddy"]
    total_sessions    = sessions_as_owner + sessions_as_buddy
    total_minutes     = owner_stats["minutes_as_owner"] + buddy_stats["minutes_as_buddy"]
    total_hours       = round(total_minutes / 60, 1)

    cur.close(); db.close()

    achievements = _compute_achievements(
        sessions=total_sessions,
        slots=sessions_as_owner,
        friends_count=len(friends),
        rating=float(user["user_rating"] or 0),
        rating_count=user["rating_count"],
    )
    title = get_title(float(user["user_rating"] or 0), total_sessions)
    return render_template("profile.html",
        user=user,
        username=user["user_name"],
        user_rating=float(user["user_rating"] or 0),
        rating_count=user["rating_count"],
        avatar_id=user["avatar_id"],
        avatars=AVATARS,
        friends=friends,
        sessions_joined=sessions_as_buddy,
        slots_posted=sessions_as_owner,
        total_sessions=total_sessions,
        total_hours=total_hours,
        achievements=achievements,
        title=title,
        notif_count=get_notif_count(user_id),
    )


@app.route("/profile/<int:uid>")
@login_required
def user_profile(uid):
    #viewing other user profiles 
    viewer_id =session["user_id"]
    if uid ==viewer_id:
        return redirect(url_for("profile"))
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT * FROM users WHERE user_id = %s", (uid,))
    user = cur.fetchone()
    if not user:
        cur.close(); db.close()
        flash("User not found.", "error")
        return redirect(url_for("session_page"))
    # Stats from completed_sessions
    cur.execute("""
        SELECT COUNT(DISTINCT cs.id) AS sessions_as_owner,
               COALESCE(SUM(cs.minutes_run), 0) AS minutes_as_owner
        FROM completed_sessions cs WHERE cs.owner_id = %s
    """, (uid,))
    owner_stats = cur.fetchone()

    cur.execute("""
        SELECT COUNT(DISTINCT csp.completed_session_id) AS sessions_as_buddy,
               COALESCE(SUM(cs.minutes_run), 0) AS minutes_as_buddy
        FROM completed_session_participants csp
        JOIN completed_sessions cs ON cs.id = csp.completed_session_id
        WHERE csp.user_id = %s AND cs.owner_id != %s
    """, (uid, uid))
    buddy_stats = cur.fetchone()

    sessions_as_owner = owner_stats["sessions_as_owner"]
    sessions_as_buddy = buddy_stats["sessions_as_buddy"]
    total_sessions    = sessions_as_owner + sessions_as_buddy
    total_minutes     = owner_stats["minutes_as_owner"] + buddy_stats["minutes_as_buddy"]
    total_hours       = round(total_minutes / 60, 1)

    # Friends count for this user
    cur.execute("SELECT COUNT(*) AS cnt FROM friends WHERE user_id_1=%s OR user_id_2=%s", (uid, uid))
    friends_count = cur.fetchone()["cnt"]

    # Is viewer friends with this user?
    u1, u2 = min(viewer_id, uid), max(viewer_id, uid)
    cur.execute("SELECT 1 FROM friends WHERE user_id_1=%s AND user_id_2=%s", (u1, u2))
    is_friend = cur.fetchone() is not None

    cur.close(); db.close()

    title = get_title(float(user["user_rating"] or 0), total_sessions)
    achievements = _compute_achievements(
        sessions=total_sessions,
        slots=sessions_as_owner,
        friends_count=friends_count,
        rating=float(user["user_rating"] or 0),
        rating_count=user["rating_count"],
    )

    return render_template("user_profile.html",
        user=user,
        username=user["user_name"],
        user_rating=float(user["user_rating"] or 0),
        rating_count=user["rating_count"],
        avatar_id=user["avatar_id"],
        avatars=AVATARS,
        sessions_joined=sessions_as_buddy,
        slots_posted=sessions_as_owner,
        total_sessions=total_sessions,
        total_hours=total_hours,
        achievements=achievements,
        title=title,
        is_friend=is_friend,
        notif_count=get_notif_count(viewer_id),
    )


def _compute_achievements(sessions, slots, friends_count, rating, rating_count):
    return [
        {"icon": "🌱", "name": "First Step",       "desc": "Post your first slot",    "unlocked": slots >= 1},
        {"icon": "🤝", "name": "First Buddy",       "desc": "Join a session",          "unlocked": sessions >= 1},
        {"icon": "📚", "name": "Study Group",       "desc": "Join 5 sessions",         "unlocked": sessions >= 5},
        {"icon": "⭐", "name": "Well Rated",        "desc": "Get a 4.0+ avg rating",   "unlocked": rating >= 4.0 and rating_count >= 3},
        {"icon": "👥", "name": "Social Butterfly",  "desc": "Add 3 study buddies",     "unlocked": friends_count >= 3},
        {"icon": "🏆", "name": "Elite Scholar",     "desc": "Complete 20+ sessions",   "unlocked": sessions >= 20},
    ]


#changing avatar method 
@app.route("/update_avatar", methods=["POST"])
@login_required
def update_avatar():
    user_id   =session["user_id"]
    avatar_id =int(request.form.get("avatar_id", 0))
    db =get_db()
    cur =db.cursor()
    cur.execute("UPDATE users SET avatar_id=%s WHERE user_id=%s", (avatar_id, user_id))
    db.commit()
    cur.close(); db.close()
    return redirect(url_for("profile"))


#change password method 
@app.route("/change_password", methods=["POST"])
@login_required
def change_password():
    user_id = session["user_id"]
    old_pw  = request.form.get("old_password", "")
    new_pw  = request.form.get("new_password", "")
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute("SELECT user_password FROM users WHERE user_id=%s", (user_id,))
    user = cur.fetchone()
    if not bcrypt.checkpw(old_pw.encode('utf-8'), user["user_password"].encode('utf-8')):
        flash("Current password is incorrect.", "error")
    elif len(new_pw) < 6:
        flash("New password must be at least 6 characters.", "error")
    else:
        hashed = bcrypt.hashpw(new_pw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cur.execute("UPDATE users SET user_password=%s WHERE user_id=%s", (hashed, user_id))
        db.commit()
        flash("Password updated!", "success")
    cur.close(); db.close()
    return redirect(url_for("profile"))
    

#Delete method 
@app.route("/delete_account", methods=["POST"])
@login_required
def delete_account():
    user_id = session["user_id"]
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM users WHERE user_id=%s", (user_id,))
    db.commit()
    cur.close(); db.close()
    session.clear()
    flash("Account deleted.", "success")
    return redirect(url_for("login"))



#Background music feature 

MUSIC_SNIPPET = """
<!-- ── Persistent Background Music ── -->
<button id="musicToggle"
  title="Toggle background music"
  style="
    position:fixed; bottom:4.5rem; right:1.5rem; z-index:9999;
    width:42px; height:42px; border-radius:50%;
    background:#E69BFF; border:1.5px solid #333;
    font-size:1.2rem; cursor:pointer;
    display:flex; align-items:center; justify-content:center;
    box-shadow:0 2px 8px rgba(0,0,0,0.18);
    transition: background 0.2s;
  ">🎵</button>

<script>
(function(){
  var btn     = document.getElementById('musicToggle');
  var playing = localStorage.getItem('swb_music') === 'on';
  var audio   = null;

  function getAudio() {
    if (!audio) {
      audio = new Audio('/static/music/music.wav');
      audio.loop = true;
    }
    return audio;
  }

  function applyState() {
    if (playing) {
      getAudio().play().catch(function(){});
      btn.textContent = '🔊';
      btn.style.background = '#c9f0a0';
    } else {
      if (audio) audio.pause();
      btn.textContent = '🎵';
      btn.style.background = '#E69BFF';
    }
  }

  btn.addEventListener('click', function(){
    playing = !playing;
    localStorage.setItem('swb_music', playing ? 'on' : 'off');
    applyState();
  });

  document.addEventListener('DOMContentLoaded', applyState);
})();
</script>
"""


AUTO_REFRESH_SNIPPET = """
<!-- ── Auto-refresh for home page (slots list) ── -->
<script>
(function(){
  // Only run on the home/slots page
  if (!window.location.pathname.startsWith('/home')) return;
  // Reload every 30 seconds so slot additions/deletions show up for all users
  setInterval(function(){ window.location.reload(); }, 30000);
})();
</script>
"""


@app.after_request
def inject_music(response):
    #injecting music toggle onto website
    #appears in all pages 
    ct = response.content_type or ""
    if "text/html" in ct:
        if request.path == "/music_player":
            return response
        data = response.get_data(as_text=True)
        if "</body>" in data:
            data = data.replace("</body>", MUSIC_SNIPPET + AUTO_REFRESH_SNIPPET + "\n</body>", 1)
            response.set_data(data)
    return response

#run app 
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
