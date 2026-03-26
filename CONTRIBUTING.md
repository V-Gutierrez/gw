# Contributing to gw

Thanks for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/v-gutierrez/gw.git
cd gw
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest
```

## Code Style

- Python 3.11+
- Type hints encouraged
- Follow existing patterns in `src/gw/services/`

## Pull Requests

1. Fork the repo
2. Create a feature branch (`git checkout -b feat/my-feature`)
3. Commit with conventional commits (`feat:`, `fix:`, `docs:`)
4. Push and open a PR

## Reporting Issues

Open an issue with:
- What you expected
- What happened
- Steps to reproduce
- `gw --version` output
