import sys
import subprocess
import json
import os
import time
import dbus
import dbus.mainloop.glib
from gi.repository import GLib
import notify2

LOG_FILE = os.path.expanduser("~/.cache/swaync_history.json")
INDEX_FILE = os.path.expanduser("~/.cache/swaync_pop_index")
MAX_NOTIFS = 100
IGNORE_APP = "ReplayLogger"


def save_notif(notif):
    if notif.get("app_name") == IGNORE_APP:
        return

    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(notif) + "\n")

    try:
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()
        if len(lines) > MAX_NOTIFS:
            with open(LOG_FILE, "w") as f:
                f.writelines(lines[-MAX_NOTIFS:])
    except FileNotFoundError:
        pass


def notify_handler(
    app_name, replaces_id, app_icon, summary, body, actions, hints, expire_timeout
):
    if app_name == IGNORE_APP:
        return

    notif = {
        "app_name": app_name,
        "replaces_id": replaces_id,
        "app_icon": app_icon,
        "summary": summary,
        "body": body,
        "actions": list(actions) if actions else [],
        "hints": dict(hints) if hints else {},
        "expire_timeout": expire_timeout,
        "timestamp": time.time(),
    }

    hints_clean = {}
    for key, value in notif["hints"].items():
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
    notif["hints"] = hints_clean

    save_notif(notif)


def run_daemon():
    print(f"Started Notification Logger (saving to {LOG_FILE})")
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


def pop(direction="back"):
    try:
        if time.time() - os.path.getmtime(INDEX_FILE) > 15:
            idx = 0
        else:
            with open(INDEX_FILE, "r") as f:
                idx = int(f.read().strip())
    except (FileNotFoundError, ValueError):
        idx = 0

    if direction == "forward":
        if idx > 0:
            subprocess.run(["swaync-client", "--hide-latest"])
            idx -= 1
            with open(INDEX_FILE, "w") as f:
                f.write(str(idx))
        return

    idx += 1

    try:
        with open(LOG_FILE, "r") as f:
            logs = [json.loads(line) for line in f if line.strip()]
    except (FileNotFoundError, json.JSONDecodeError):
        return

    if idx > len(logs):
        idx = len(logs)

    if not logs:
        return

    log = logs[-idx]

    summary = f"[History: {idx}] {log.get('summary', '')}"
    body = log.get("body", "")

    urgency = None
    hints = log.get("hints", {})
    if "urgency" in hints:
        urgency = hints.pop("urgency")

    send_notification(
        summary=summary,
        body=body,
        app_name=log.get("app_name"),
        icon=log.get("app_icon"),
        hints=hints,
        actions=log.get("actions"),
        expire_timeout=log.get("expire_timeout", -1),
        urgency=urgency,
    )

    with open(INDEX_FILE, "w") as f:
        f.write(str(idx))


def replay(count):
    try:
        with open(LOG_FILE, "r") as f:
            logs = [json.loads(line) for line in f if line.strip()]
    except (FileNotFoundError, json.JSONDecodeError):
        return

    to_replay = logs[-count:] if count > 0 else logs

    for log in to_replay:
        summary = f"[replay: {log.get('app_name', 'Unknown')}] {log.get('summary', '')}"
        body = log.get("body", "")

        urgency = None
        hints = log.get("hints", {})
        if "urgency" in hints:
            urgency = hints.pop("urgency")

        send_notification(
            summary=summary,
            body=body,
            app_name=log.get("app_name"),
            icon=log.get("app_icon"),
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
