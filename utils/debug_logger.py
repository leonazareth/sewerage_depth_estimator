# -*- coding: utf-8 -*-
"""
Centralized debug logging utilities for sewerage depth estimator plugin.
"""

import functools
from typing import Any, Optional


class DebugLogger:
    """Centralized debug logging with consistent formatting."""
    
    PREFIX = "[SEWERAGE DEBUG]"
    
    @classmethod
    def log(cls, message: str, *args) -> None:
        """Log a debug message with consistent formatting."""
        formatted_msg = message
        if args:
            try:
                formatted_msg = message.format(*args)
            except (IndexError, KeyError):
                formatted_msg = f"{message} {args}"
        print(f"{cls.PREFIX} {formatted_msg}")
    
    @classmethod
    def log_error(cls, message: str, exception: Optional[Exception] = None) -> None:
        """Log an error message with optional exception details."""
        if exception:
            cls.log(f"ERROR: {message}: {exception}")
        else:
            cls.log(f"ERROR: {message}")
    
    @classmethod
    def log_method_entry(cls, method_name: str, *args) -> None:
        """Log entry to a method with arguments."""
        args_str = ", ".join(str(arg) for arg in args) if args else ""
        cls.log(f"-> {method_name}({args_str})")
    
    @classmethod
    def log_feature_processing(cls, feature_id: Any, action: str, **kwargs) -> None:
        """Log feature processing actions."""
        details = ", ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
        cls.log(f"Feature {feature_id}: {action} {details}")


def debug_method(func):
    """Decorator to automatically log method entry and exceptions."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        method_name = f"{func.__qualname__}"
        DebugLogger.log_method_entry(method_name)
        try:
            return func(*args, **kwargs)
        except Exception as e:
            DebugLogger.log_error(f"Exception in {method_name}", e)
            raise
    return wrapper