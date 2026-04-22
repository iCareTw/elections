# Repository Guidelines

## Project Structure & Module Organization
This repository builds two maintained YAML outputs: `candidates.yaml` and `election_types.yaml`. Runtime code lives in `src/`, with focused modules such as `parse_*.py`, `merge.py`, `normalize.py`, and `validate.py`. The CLI entrypoint is `main.py`. Tests are split into `tests/unit/` and `tests/integration/`. Session-specific YAML files like `6th.yaml` through `11th.yaml` hold legislator data, while `docs/superpowers/specs/` and `docs/superpowers/plans/` capture design and implementation history.

## Build, Test, and Development Commands
Use `uv` for all Python commands.

- `uv run python main.py`: run the repository entrypoint.
- `make test`: run the full test suite (`tests/unit` and `tests/integration`).
- `make test-unit`: run unit tests only.
- `make test-integration`: run integration tests only.
- `uv run pytest tests/unit/test_normalize.py -v`: run a single test file while iterating.

## Coding Style & Naming Conventions
Follow the existing Python style: 4-space indentation, small single-purpose functions, and type hints where useful. Keep module names lowercase with underscores, and mirror existing patterns such as `parse_president.py` and `test_merge.py`. Prefer descriptive helpers with leading underscores for internal functions. Preserve repository data conventions exactly, including canonical field names and stable YAML schema. No formatter or linter is configured today, so match the surrounding code closely and keep diffs minimal.

## Testing Guidelines
Tests use `pytest`. Add unit tests for normalization, parsing, merging, and validation logic; add integration tests when behavior spans multiple modules or output files. Name test files `test_<module>.py` and test functions `test_<behavior>()`. Cover both expected output and edge cases, especially record matching and ID generation.

## Commit & Pull Request Guidelines
Recent history uses short prefixes such as `feat:`, `impl:`, `test:`, `docs:`, and `chore:`. Keep commit subjects concise and scoped to one change, for example `impl: add 11th party-list data`. Pull requests should explain the affected election data or parsing logic, list the commands run for verification, and note any output-file changes to `candidates.yaml` or `election_types.yaml`. Include sample YAML snippets only when they help reviewers inspect schema changes quickly.
