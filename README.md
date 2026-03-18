# swaync-history

Notification history logger and replayer for [swaync](https://github.com/ErikReider/SwayNotificationCenter).

Logs all notifications to a SQLite database and allows browsing history via scroll integration with waybar.

## Features

- Captures all D-Bus notifications using native monitoring API
- Stores notifications in SQLite database with full metadata
- Serializes and replays file icons (preserves images even after original files are deleted)
- Scroll through notification history via waybar integration
- Replay missed notifications

## Installation

```bash
# From GitHub
uvx --from git+https://github.com/adrianlzt/swaync-history swaync-history

# Or clone and install
git clone https://github.com/adrianlzt/swaync-history
cd swaync-history
uv pip install .
```

## Usage

### Start the daemon

```bash
swaync-history daemon
```

This starts monitoring D-Bus for all notifications and stores them in `~/.cache/swaync_history.db`.

### Replay notifications

```bash
# Replay last 5 notifications
swaync-history replay

# Replay last N notifications
swaync-history replay 10
```

### Browse history

```bash
# Show older notification (scroll down)
swaync-history pop back

# Hide latest notification (scroll up)
swaync-history pop forward
```

## Waybar Integration

Add a custom module to your waybar config:

```json
"custom/notification-scroll": {
    "format": "notif",
    "on-scroll-up": "swaync-history pop forward",
    "on-scroll-down": "swaync-history pop back",
    "tooltip": false
}
```

When you scroll on this module:
- **Scroll down**: Shows older notifications from history
- **Scroll up**: Hides the current notification (calls `swaync-client --hide-latest`)

### Autostart

Add to your sway config to start the daemon on login:

```
exec swaync-history daemon
```

Or use a systemd user service.

## Data Stored

Each notification captures:

| Field | Description |
|-------|-------------|
| `app_name` | Application name |
| `replaces_id` | ID of notification this replaces |
| `app_icon` | Icon name or path |
| `icon_data` | Serialized icon (base64) for file icons |
| `summary` | Notification title |
| `body` | Notification body |
| `actions` | Available actions |
| `hints` | Additional hints (urgency, etc.) |
| `expire_timeout` | Timeout in milliseconds |
| `timestamp` | When notification was received |

## Files

| File | Description |
|------|-------------|
| `~/.cache/swaync_history.db` | SQLite database with notification history |
| `~/.cache/swaync_pop_index` | Current scroll position index |
| `/tmp/swaync-history/icons/` | Temporary directory for replayed icons |

## Icon Handling

- **Named icons** (e.g., `firefox`, `chrome`): Stored by name, resolved by theme on replay
- **File icons** (e.g., `/tmp/.../logo.png`): Serialized to base64, recreated on replay
- **URL icons**: Skipped (not supported)

Icons are stored in `/tmp/swaync-history/icons/` and automatically cleaned on reboot.

## Requirements

- Python 3.12+
- D-Bus session bus
- [swaync](https://github.com/ErikReider/SwayNotificationCenter) (for `swaync-client`)

## License

MIT
