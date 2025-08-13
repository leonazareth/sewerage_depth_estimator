# -*- coding: utf-8 -*-
"""
Debug control for sewerage depth estimator plugin.

Quick way to enable/disable debug logging:
- To enable: from .debug_control import enable_debug; enable_debug()
- To disable: from .debug_control import disable_debug; disable_debug()
"""

from .utils import DebugLogger


def enable_debug():
    """Enable all debug logging."""
    DebugLogger.enable()
    print("✅ Debug logging enabled for sewerage depth estimator")


def disable_debug():
    """Disable all debug logging."""
    DebugLogger.disable()
    print("🔇 Debug logging disabled for sewerage depth estimator")


# By default, debug is disabled
disable_debug()
