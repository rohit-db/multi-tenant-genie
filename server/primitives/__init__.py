"""Databricks primitives — the "Databricks is all you need" layer.

Each module here wraps exactly one Databricks Data Intelligence Platform
capability behind a small, swappable interface. The services layer composes
them; nothing here knows about HTTP or about the other primitives.

See ``README.md`` for the capability-to-module map.
"""
