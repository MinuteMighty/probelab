# Contributing to probelab

Thanks for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/MinuteMighty/probelab.git
cd probelab
uv pip install -e ".[dev]"
```

## Running Tests

```bash
uv run python -m pytest tests/ -v
```

## Adding a New Feature

1. Create a branch: `git checkout -b feature/my-feature`
2. Write tests first in `tests/`
3. Implement in `src/probelab/`
4. Run the full test suite
5. Open a PR

## Code Style

- Type hints on all public functions
- Docstrings on modules and classes
- No dependencies beyond what's in `pyproject.toml` without discussion

## Reporting Bugs

Open a GitHub issue with:
- probelab version (`probelab --version`)
- Python version
- The probe definition that triggers the bug
- Expected vs actual behavior
