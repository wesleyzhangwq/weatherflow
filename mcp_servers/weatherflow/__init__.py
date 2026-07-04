"""Unified WeatherFlow MCP server.

One server exposing the full MCP surface — tools (with annotations),
resources, and prompts — over stdio or streamable HTTP.

The two legacy per-domain servers (``weatherflow_calendar`` /
``weatherflow_github``) remain the *definition point* for tool wrappers;
this package aggregates them and adds everything the protocol offers
beyond bare tools. Existing hosts pointed at the legacy entry points
keep working unchanged.
"""
