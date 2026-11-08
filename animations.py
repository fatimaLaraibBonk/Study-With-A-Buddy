#ANIMATION MODULE 

import json

ANIMATION_SNIPPET = """
<!-- ── Event Animations (Feature 5) ── -->
<style>
  #swb-toast-container {
    position: fixed; top: 1.2rem; right: 1.2rem;
    z-index: 99999; display: flex; flex-direction: column; gap: 0.6rem;
    pointer-events: none;
  }
  .swb-toast {
    min-width: 260px; max-width: 340px;
    padding: 14px 18px; border-radius: 12px;
    font-family: Arial, sans-serif; font-size: 0.92rem; font-weight: 600;
    display: flex; align-items: center; gap: 10px;
    box-shadow: 0 4px 18px rgba(0,0,0,0.18);
    pointer-events: all;
    transform: translateX(110%);
    animation: swb-slide-in 0.4s cubic-bezier(.22,1,.36,1) forwards,
               swb-slide-out 0.4s ease-in 3.6s forwards;
  }
  @keyframes swb-slide-in  { to { transform: translateX(0); } }
  @keyframes swb-slide-out { to { transform: translateX(110%); opacity:0; } }

  .swb-toast.accepted { background:#d4f7d4; border:2px solid #4caf50; color:#1b5e20; }
  .swb-toast.rejected { background:#fde8e8; border:2px solid #e53935; color:#b71c1c; }
  .swb-toast.starting { background:#f0e6ff; border:2px solid #9c27b0; color:#4a148c; }
  .swb-toast.ending   { background:#fff3e0; border:2px solid #ff9800; color:#e65100; }
  .swb-toast .swb-icon { font-size: 1.4rem; flex-shrink: 0; }

  @keyframes swb-shake {
    0%,100%{transform:translateX(0)}
    15%{transform:translateX(-8px)}
    30%{transform:translateX(8px)}
    45%{transform:translateX(-6px)}
    60%{transform:translateX(6px)}
    75%{transform:translateX(-3px)}
    90%{transform:translateX(3px)}
  }
  .swb-shake { animation: swb-shake 0.55s ease both !important; }

  #swb-confetti-canvas {
    position:fixed; inset:0; pointer-events:none; z-index:99998;
  }

  .swb-pulse-ring {
    position:fixed; top:50%; left:50%; width:60px; height:60px;
    margin:-30px 0 0 -30px; border-radius:50%;
    border:4px solid #9c27b0;
    animation: swb-pulse-ring 0.8s ease-out forwards;
    pointer-events:none; z-index:99998;
  }
  @keyframes swb-pulse-ring {
    0%   { transform:scale(0.5); opacity:1; }
    100% { transform:scale(6);   opacity:0; }
  }

  .swb-end-veil {
    position:fixed; inset:0;
    background: linear-gradient(135deg,rgba(255,152,0,0.18),rgba(244,67,54,0.12));
    pointer-events:none; z-index:99997;
    animation: swb-veil-fade 2.5s ease forwards;
  }
  @keyframes swb-veil-fade {
    0%   { opacity:0; }
    30%  { opacity:1; }
    100% { opacity:0; }
  }
</style>

<canvas id="swb-confetti-canvas"></canvas>
<div id="swb-toast-container"></div>

<script>
(function(){
  function showToast(type, icon, message) {
    var container = document.getElementById('swb-toast-container');
    var t = document.createElement('div');
    t.className = 'swb-toast ' + type;
    t.innerHTML = '<span class="swb-icon">' + icon + '</span><span>' + message + '</span>';
    container.appendChild(t);
    setTimeout(function(){ t.remove(); }, 4200);
  }

  function launchConfetti() {
    var canvas = document.getElementById('swb-confetti-canvas');
    var ctx    = canvas.getContext('2d');
    canvas.width  = window.innerWidth;
    canvas.height = window.innerHeight;
    var pieces = [];
    var COLORS = ['#4caf50','#8bc34a','#E69BFF','#ffeb3b','#03a9f4','#ff9800'];
    for (var i = 0; i < 110; i++) {
      pieces.push({
        x: Math.random() * canvas.width,
        y: -10 - Math.random() * 80,
        r: 5 + Math.random() * 6,
        color: COLORS[Math.floor(Math.random() * COLORS.length)],
        vx: (Math.random() - 0.5) * 4,
        vy: 2 + Math.random() * 4,
        rot: Math.random() * 360,
        vrot: (Math.random() - 0.5) * 6,
        alpha: 1,
      });
    }
    var start = null;
    function draw(ts) {
      if (!start) start = ts;
      var elapsed = ts - start;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      pieces.forEach(function(p){
        p.x += p.vx; p.y += p.vy; p.rot += p.vrot;
        if (elapsed > 1800) p.alpha = Math.max(0, p.alpha - 0.018);
        ctx.save();
        ctx.globalAlpha = p.alpha;
        ctx.fillStyle   = p.color;
        ctx.translate(p.x, p.y);
        ctx.rotate(p.rot * Math.PI / 180);
        ctx.fillRect(-p.r/2, -p.r/2, p.r, p.r * 1.6);
        ctx.restore();
      });
      if (elapsed < 3200) requestAnimationFrame(draw);
      else ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
    requestAnimationFrame(draw);
  }

  function shakeLatestToast() {
    var toasts = document.querySelectorAll('.swb-toast.rejected');
    if (toasts.length) toasts[toasts.length-1].classList.add('swb-shake');
  }

  function pulseRing() {
    var ring = document.createElement('div');
    ring.className = 'swb-pulse-ring';
    document.body.appendChild(ring);
    setTimeout(function(){ ring.remove(); }, 900);
  }

  function endVeil() {
    var veil = document.createElement('div');
    veil.className = 'swb-end-veil';
    document.body.appendChild(veil);
    setTimeout(function(){ veil.remove(); }, 2600);
  }

  document.addEventListener('DOMContentLoaded', function(){
    var eventsEl = document.getElementById('swb-anim-events');
    if (!eventsEl) return;
    var events = JSON.parse(eventsEl.textContent || '[]');
    events.forEach(function(ev, idx){
      setTimeout(function(){
        if (ev === 'accepted') {
          launchConfetti();
          showToast('accepted', '✅', 'Your request was accepted! Head to Your Session.');
        } else if (ev === 'rejected') {
          showToast('rejected', '❌', 'Your request was declined.');
          setTimeout(shakeLatestToast, 50);
        } else if (ev === 'starting') {
          pulseRing();
          setTimeout(pulseRing, 200);
          showToast('starting', '🚀', 'Your study slot is now live!');
        } else if (ev === 'ending') {
          endVeil();
          showToast('ending', '⏰', 'A study session has ended.');
        }
      }, idx * 400);
    });
  });
})();
</script>
"""


def push_anim_event(session, event: str):
    """
    Queue an animation for the current user's *next* response in the same
    request cycle (i.e. the redirect target page).

    Use this when the acting user IS the one who should see the animation.
    Example: owner posts a slot -> push_anim_event(session, 'starting')
    """
    session.setdefault("_anim_events", []).append(event)


def register_animations(app, get_db):
    """
    Attach the after_request hook to inject animations into every HTML response.

    Call this once from SWB.py after the app is created:
        register_animations(app, get_db)

    Pass `get_db` so the hook can query the `anim_events` table for
    cross-request events queued by background threads or other users' routes.
    """

    @app.after_request
    def inject_animations(response):
        from flask import session as flask_session

        ct = response.content_type or ""
        if "text/html" not in ct:
            return response
        data = response.get_data(as_text=True)
        if "</body>" not in data:
            return response

        # 1. Same-request events (stored in Flask session)
        events = list(flask_session.pop("_anim_events", []))

        # 2. Cross-request / background-thread events (stored in DB)
        user_id = flask_session.get("user_id")
        if user_id:
            try:
                db  = get_db()
                cur = db.cursor(dictionary=True)
                cur.execute(
                    "SELECT id, event_type FROM anim_events "
                    "WHERE user_id = %s ORDER BY created_at ASC",
                    (user_id,)
                )
                rows = cur.fetchall()
                if rows:
                    ids = [r["id"] for r in rows]
                    fmt = ",".join(["%s"] * len(ids))
                    cur.execute(f"DELETE FROM anim_events WHERE id IN ({fmt})", ids)
                    db.commit()
                    events.extend(r["event_type"] for r in rows)
                cur.close()
                db.close()
            except Exception as e:
                print(f"[animations] DB fetch error: {e}")

        # 3. Inject into the page
        events_json = json.dumps(events)
        events_tag  = (
            f'<script id="swb-anim-events" type="application/json">'
            f'{events_json}</script>\n'
        )
        data = data.replace("</body>", events_tag + ANIMATION_SNIPPET + "\n</body>", 1)
        response.set_data(data)
        return response
