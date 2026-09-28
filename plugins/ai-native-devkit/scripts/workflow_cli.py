#!/usr/bin/env python3
"""Versioned JSON entry point for durable AI Native DevKit workflow state."""

import sys

from ai_native_devkit.workflow_cli import main


if __name__ == "__main__":
    sys.exit(main())
