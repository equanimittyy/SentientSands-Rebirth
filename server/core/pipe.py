import time

def send_to_pipe(cmd):
    """The plugin dispatches on these prefixes; anything else is sent as a "CMD: " command."""
    if not (cmd.startswith("CMD:") or cmd.startswith("NPC_") or cmd.startswith("PLAYER_") or cmd.startswith("NOTIFY:")):
        cmd = "CMD: " + cmd

    # The plugin re-creates its only pipe instance after each message, so a send right after another one can find no instance for a moment
    deadline = time.monotonic() + 0.25
    while True:
        try:
            with open(r'\\.\pipe\SentientSands', 'wb') as f:
                f.write(cmd.encode('utf-8'))
            return
        except OSError:
            if time.monotonic() >= deadline:
                return
            time.sleep(0.01)
