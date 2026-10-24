"""Send an alert from a shell script: platform_util.notify (Discord webhook when OWCSKR_DISCORD_WEBHOOK is set, a
message box on a Windows desktop without one, always stderr).
usage: python -I tools/notify.py "TITLE" "BODY"      (BODY '-' = read it from stdin)
Always exits 0: a failed alert must never turn a job's result into something else."""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')   # Korean text on a cp949 console
        import platform_util as PU
        if len(argv) < 2:
            print('usage: notify.py TITLE BODY', file=sys.stderr)
            return 0
        title, body = argv[0], argv[1]
        if body == '-':
            body = sys.stdin.read()
        try:
            PU.load_env_file()          # run by hand outside the tools/*.sh scripts: still find the webhook
        except ValueError as e:
            print(f'notify: .env not loaded: {e}', file=sys.stderr)
        PU.notify(title, body.strip() or '(no details)')
    except Exception as e:      # never fail the caller
        print(f'notify: failed: {type(e).__name__}: {e}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
