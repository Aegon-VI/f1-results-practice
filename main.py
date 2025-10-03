import os, json, requests, datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

OPENF1 = "https://api.openf1.org/v1"
STATE_FILE = Path("state.json")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK")
TOP_N = int(os.environ.get("TOP_N", "10"))
LOCAL_TZ = os.environ.get("LOCAL_TZ", "Europe/Amsterdam")

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {"last_posted_session_key": None}
    return {"last_posted_session_key": None}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))

def get_latest_practice_session():
    # Pull latest meeting, then choose the newest Practice session by end time
    r = requests.get(f"{OPENF1}/sessions", params={"meeting_key": "latest"}, timeout=20)
    r.raise_for_status()
    sessions = r.json()
    practice = [s for s in sessions if (s.get("session_type") == "Practice")]
    if not practice:
        return None
    def sort_key(s):
        return s.get("date_end") or s.get("date_start") or ""
    practice.sort(key=sort_key)
    return practice[-1]

def get_session_results(session_key):
    r = requests.get(f"{OPENF1}/session_result", params={"session_key": session_key}, timeout=20)
    r.raise_for_status()
    rows = r.json()
    return sorted(rows, key=lambda x: x.get("position") or 9999)

def format_when(meta):
    # Convert API time to local timezone for the title
    iso = meta.get("date_end") or meta.get("date_start")
    if not iso:
        return ""
    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        local = t.astimezone(ZoneInfo(LOCAL_TZ))
        return local.strftime("%a %d %b %Y %H:%M %Z")
    except Exception:
        return iso

def post_to_discord(title, lines):
    if not DISCORD_WEBHOOK:
        print("No DISCORD_WEBHOOK provided.")
        return
    payload = {"content": f"**{title}**\n" + "\n".join(lines)}
    requests.post(DISCORD_WEBHOOK, json=payload, timeout=20)

def main():
    state = load_state()
    sess = get_latest_practice_session()
    if not sess:
        print("No practice session found.")
        return

    sk = sess.get("session_key")
    if not sk:
        print("Session has no key.")
        return

    # De-dupe: only post once per session
    if state.get("last_posted_session_key") == sk:
        print("Already posted this session; skipping.")
        return

    results = get_session_results(sk)
    if not results:
        print("No results yet; try again next run.")
        return

    # Build message
    gp = sess.get("meeting_name") or sess.get("country_name") or "Grand Prix"
    sname = sess.get("session_name") or "Practice"
    when = format_when(sess)

    lines = []
    for row in results[:TOP_N]:
        pos = row.get("position")
        first = (row.get("driver_first_name") or "")[:1]
        last = row.get("driver_last_name") or ""
        name = f"{first}. {last}".strip(". ")
        team = row.get("team_name") or ""
        lap = row.get("best_lap_time") or row.get("time") or ""
        lines.append(f"{pos}. {name} — {team}  {lap}")

    title = f"{gp} — {sname} Results ({when})"
    post_to_discord(title, lines)

    # Mark posted
    state["last_posted_session_key"] = sk
    save_state(state)
    print(f"Posted session {sk}.")

if __name__ == "__main__":
    main()
