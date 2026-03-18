import sys
import subprocess
import json
import os
import time
import sqlite3
import base64
import dbus
import dbus.mainloop.glib
from gi.repository import GLib
import notify2

DB_FILE = os.path.expanduser("~/.cache/swaync_history.db")
INDEX_FILE = os.path.expanduser("~/.cache/swaync_pop_index")
ICON_DIR = "/tmp/swaync-history/icons"
MAX_NOTIFS = 100
IGNORE_APP = "ReplayLogger"

ICON_SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpg",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
    b"RIFF": "webp",
    b"\x00\x00\x01\x00": "ico",
    b"BM": "bmp",
}


def detect_image_type(data):
    for sig, ext in ICON_SIGNATURES.items():
        if data.startswith(sig):
            return ext
    return "png"


def serialize_icon(path):
    if not path:
        return None, None
    if path.startswith(("http://", "https://")):
        return None, None
    local_path = path.replace("file://", "")
    if not os.path.isabs(local_path):
        return None, None
    try:
        with open(local_path, "rb") as f:
            data = f.read()
        ext = detect_image_type(data)
        return base64.b64encode(data).decode("utf-8"), ext
    except (FileNotFoundError, PermissionError):
        return None, None


def deserialize_icon(icon_data, ext, notif_id):
    if not icon_data:
        return None
    os.makedirs(ICON_DIR, exist_ok=True)
    filename = f"notif_{notif_id}.{ext}"
    filepath = os.path.join(ICON_DIR, filename)
    data = base64.b64decode(icon_data)
    with open(filepath, "wb") as f:
        f.write(data)
    return filepath


def get_db():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_name TEXT,
            replaces_id INTEGER,
            app_icon TEXT,
            icon_data TEXT,
            summary TEXT,
            body TEXT,
            actions TEXT,
            hints TEXT,
            expire_timeout INTEGER,
            timestamp REAL
        )
    """)
    try:
        conn.execute("ALTER TABLE notifications ADD COLUMN icon_data TEXT")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    return conn


def save_notif(notif):
    if notif.get("app_name") == IGNORE_APP:
        return

    icon_path = notif.get("app_icon") or ""
    hints = notif.get("hints", {})

    for hint_key in ["image-path", "image_path", "icon_data"]:
        if hint_key in hints:
            icon_path = hints[hint_key]
            break

    icon_data, icon_ext = serialize_icon(icon_path)
    if icon_data:
        icon_data = f"{icon_ext}:{icon_data}"

    conn = get_db()
    conn.execute(
        """
        INSERT INTO notifications
        (app_name, replaces_id, app_icon, icon_data, summary, body, actions, hints, expire_timeout, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            notif["app_name"],
            notif["replaces_id"],
            notif["app_icon"],
            icon_data,
            notif["summary"],
            notif["body"],
            json.dumps(notif["actions"]),
            json.dumps(notif["hints"]),
            notif["expire_timeout"],
            notif["timestamp"],
        ),
    )

    conn.execute(
        "DELETE FROM notifications WHERE id NOT IN "
        "(SELECT id FROM notifications ORDER BY timestamp DESC LIMIT ?)",
        (MAX_NOTIFS,),
    )
    conn.commit()
    conn.close()


def notify_handler(
    app_name, replaces_id, app_icon, summary, body, actions, hints, expire_timeout
):
    if app_name == IGNORE_APP:
        return

    hints_clean = {}
    for key, value in (hints or {}).items():
        if isinstance(value, dbus.Boolean):
            hints_clean[key] = bool(value)
        elif isinstance(value, dbus.Int32):
            hints_clean[key] = int(value)
        elif isinstance(value, dbus.UInt32):
            hints_clean[key] = int(value)
        elif isinstance(value, dbus.Byte):
            hints_clean[key] = int(value)
        elif isinstance(value, dbus.Double):
            hints_clean[key] = float(value)
        elif isinstance(value, dbus.String):
            hints_clean[key] = str(value)
        else:
            hints_clean[key] = str(value)

    notif = {
        "app_name": app_name,
        "replaces_id": replaces_id,
        "app_icon": app_icon,
        "summary": summary,
        "body": body,
        "actions": list(actions) if actions else [],
        "hints": hints_clean,
        "expire_timeout": expire_timeout,
        "timestamp": time.time(),
    }

    save_notif(notif)


def run_daemon():
    print(f"Started Notification Logger (saving to {DB_FILE})")
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    bus = dbus.SessionBus()
    bus.add_match_string("interface='org.freedesktop.Notifications',member='Notify'")

    monitoring = dbus.Interface(
        bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus"),
        "org.freedesktop.DBus.Monitoring",
    )
    monitoring.BecomeMonitor(
        ["interface='org.freedesktop.Notifications',member='Notify'"], 0
    )

    bus.add_message_filter(notify_filter)

    loop = GLib.MainLoop()
    loop.run()


def notify_filter(bus, message):
    if message.get_interface() != "org.freedesktop.Notifications":
        return
    if message.get_member() != "Notify":
        return

    args = message.get_args_list()
    if len(args) >= 8:
        notify_handler(
            str(args[0]),
            int(args[1]),
            str(args[2]),
            str(args[3]),
            str(args[4]),
            args[5],
            args[6],
            int(args[7]),
        )


def send_notification(
    summary,
    body,
    app_name=None,
    icon=None,
    hints=None,
    actions=None,
    expire_timeout=-1,
    urgency=None,
):
    notify2.init(IGNORE_APP)
    n = notify2.Notification(summary, body, icon=icon or "")

    if expire_timeout > 0:
        n.set_timeout(expire_timeout)
    if urgency is not None:
        n.set_urgency(urgency)
    if hints:
        for key, value in hints.items():
            n.set_hint(key, value)
    if app_name:
        n.set_hint("desktop-entry", app_name)
    if actions:
        for i in range(0, len(actions), 2):
            if i + 1 < len(actions):
                action_key = actions[i]
                action_label = actions[i + 1]
                n.add_action(action_key, action_label, lambda *args: None)

    n.show()


def get_position():
    try:
        if time.time() - os.path.getmtime(INDEX_FILE) > 15:
            return 0
        with open(INDEX_FILE, "r") as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return 0


def set_position(idx):
    with open(INDEX_FILE, "w") as f:
        f.write(str(idx))


def get_icon_for_replay(icon_data, notif_id, original_icon):
    if icon_data:
        ext, data = icon_data.split(":", 1)
        filepath = deserialize_icon(data, ext, notif_id)
        if filepath:
            return filepath
    if original_icon and not original_icon.startswith(("http://", "https://")):
        return original_icon
    return None


def pop(direction="back"):
    idx = get_position()

    if direction == "forward":
        if idx > 0:
            subprocess.run(["swaync-client", "--hide-latest"])
            set_position(idx - 1)
        return

    idx += 1

    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]

    if idx > total:
        idx = total

    if idx < 1:
        conn.close()
        return

    row = conn.execute(
        "SELECT * FROM notifications ORDER BY timestamp DESC LIMIT 1 OFFSET ?",
        (idx - 1,),
    ).fetchone()
    conn.close()

    if not row:
        return

    log = dict(row)
    log["actions"] = json.loads(log["actions"]) if log["actions"] else []
    log["hints"] = json.loads(log["hints"]) if log["hints"] else {}

    summary = f"[History: {idx}] {log.get('summary', '')}"
    body = log.get("body", "")

    urgency = None
    hints = log.get("hints", {})
    if "urgency" in hints:
        urgency = hints.pop("urgency")

    icon = get_icon_for_replay(log.get("icon_data"), log["id"], log.get("app_icon"))

    send_notification(
        summary=summary,
        body=body,
        app_name=log.get("app_name"),
        icon=icon,
        hints=hints,
        actions=log.get("actions"),
        expire_timeout=log.get("expire_timeout", -1),
        urgency=urgency,
    )

    set_position(idx)


def replay(count):
    conn = get_db()

    if count > 0:
        rows = conn.execute(
            "SELECT * FROM notifications ORDER BY timestamp DESC LIMIT ?",
            (count,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM notifications ORDER BY timestamp DESC"
        ).fetchall()

    conn.close()

    for row in rows:
        log = dict(row)
        log["actions"] = json.loads(log["actions"]) if log["actions"] else []
        log["hints"] = json.loads(log["hints"]) if log["hints"] else {}

        summary = f"[replay: {log.get('app_name', 'Unknown')}] {log.get('summary', '')}"
        body = log.get("body", "")

        urgency = None
        hints = log.get("hints", {})
        if "urgency" in hints:
            urgency = hints.pop("urgency")

        icon = get_icon_for_replay(log.get("icon_data"), log["id"], log.get("app_icon"))

        send_notification(
            summary=summary,
            body=body,
            app_name=log.get("app_name"),
            icon=icon,
            hints=hints,
            actions=log.get("actions"),
            expire_timeout=log.get("expire_timeout", -1),
            urgency=urgency,
        )
        time.sleep(0.1)


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: swaync-history <command> [args]")
        print("Commands:")
        print("  daemon        Start the notification logger daemon")
        print("  replay [n]    Replay last n notifications (default: 5)")
        print(
            "  pop [dir]     Pop notification (direction: back/forward, default: back)"
        )
        sys.exit(0)

    command = sys.argv[1]

    if command == "daemon":
        run_daemon()
    elif command == "replay":
        count = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        replay(count)
    elif command == "pop":
        direction = sys.argv[2] if len(sys.argv) > 2 else "back"
        pop(direction)
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
