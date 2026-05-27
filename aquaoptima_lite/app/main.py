"""CLI-ish entrypoint placeholder for Optimizer Lite runtime."""

from __future__ import annotations

from ..api import create_app


def main() -> None:
    app = create_app()
    print(app)


if __name__ == "__main__":
    main()
