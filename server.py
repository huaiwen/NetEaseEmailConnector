"""Compatibility launcher for source checkouts."""
from pathlib import Path
import sys
from netease_email.cli import main

if __name__ == "__main__":
    env = Path(__file__).with_name(".env")
    main([*( ["--env-file", str(env)] if env.is_file() else []), *sys.argv[1:]])
