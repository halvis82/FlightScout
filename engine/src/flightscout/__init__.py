"""FlightScout engine: flight search, route planning and price tracking."""

__version__ = "0.1.0"


def main() -> None:
    from .cli import main as _main

    _main()
