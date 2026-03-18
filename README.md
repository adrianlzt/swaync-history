# swaync-history

Notification history logger and replayer for swaync.

## Installation

```bash
uvx swaync-history
```

## Usage

```bash
# Start the daemon (logs all notifications)
swaync-history daemon

# Replay last 5 notifications
swaync-history replay

# Replay last N notifications
swaync-history replay 10

# Scroll through history (for waybar integration)
swaync-history pop back    # Show older notification
swaync-history pop forward # Hide latest notification
```

## Waybar Integration

Add to your waybar config:

```json
"custom/notification-scroll": {
    "on-scroll-up": "swaync-history pop forward",
    "on-scroll-down": "swaync-history pop back"
}
```

## Files

- `~/.cache/swaync_history.db` - SQLite database with notification history
- `~/.cache/swaync_pop_index` - Current scroll position
