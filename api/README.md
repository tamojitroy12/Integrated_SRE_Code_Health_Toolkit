# toolkit (backend)

Python package that provides both the FastAPI application (`toolkit.api.main:app`) and the
background worker (`python -m toolkit.worker`). See the repository README and `docs/`.

```bash
uv sync                # includes the dev group (pytest, ruff, mypy)
uv run alembic upgrade head
uv run uvicorn toolkit.api.main:app --reload
uv run python -m toolkit.worker
uv run pytest
```
