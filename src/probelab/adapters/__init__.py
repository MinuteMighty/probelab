"""Probelab adapters — import probes from external adapter formats.

Each adapter is an optional importer that converts external formats to Probe YAML.
The core never depends on any adapter. Adapters are invoked via CLI commands.

Available adapters:
- opencli: Import probes from OpenCLI adapter repositories
"""
