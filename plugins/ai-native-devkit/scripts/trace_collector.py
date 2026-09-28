#!/usr/bin/env python3
"""Codex Hook entry point for execution trace collection."""

import sys

from ai_native_devkit.collector_cli import main


if __name__ == "__main__":
    sys.exit(main())
