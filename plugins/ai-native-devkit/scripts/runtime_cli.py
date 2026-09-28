#!/usr/bin/env python3
"""Versioned JSON entry point for DevKit runtime events and Docs Hook."""

import sys

from ai_native_devkit.runtime_cli import main


if __name__ == "__main__":
    sys.exit(main())
