"""Compatibility shim — real implementation is in app.providers.google_calendar_direct."""

from app.providers.google_calendar_direct import (
    GoogleCalendarConnector,
    default_calendar_token_file,
    has_calendar_credentials,
    load_calendar_access_token,
    resolve_calendar_token_file,
    sanitize_calendar_events,
)

__all__ = [
    "GoogleCalendarConnector",
    "default_calendar_token_file",
    "has_calendar_credentials",
    "load_calendar_access_token",
    "resolve_calendar_token_file",
    "sanitize_calendar_events",
]
