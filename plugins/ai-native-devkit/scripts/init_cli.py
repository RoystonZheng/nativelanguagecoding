#!/usr/bin/env python3
"""Versioned JSON command-line entry point for AI Native DevKit `/init`."""

import sys

from ai_native_devkit.cli import main


if __name__ == "__main__":
    sys.exit(main())
