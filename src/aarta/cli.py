"""Command-line interface for AARTA."""

from __future__ import annotations

import click

from aarta import __version__
from aarta.config import DEFAULT_CONFIG, TradingMode


@click.group()
@click.version_option(version=__version__, prog_name="aarta")
def main() -> None:
    """AARTA — Autonomous Adaptive Research and Trading Agent.

    Intraday trading research and paper-trading system.
    """


@main.command()
def health() -> None:
    """Run system health checks."""
    click.echo("AARTA Health Check")
    click.echo("=" * 40)
    click.echo(f"Version: {__version__}")
    click.echo(f"Trading Mode: {DEFAULT_CONFIG.trading_mode.value}")
    click.echo(f"Live Trading Enabled: {DEFAULT_CONFIG.live_trading_enabled}")
    click.echo("Status: OK (Paper-Only Mode)")


@main.command()
def mode() -> None:
    """Display current trading mode."""
    click.echo(f"Current Mode: {DEFAULT_CONFIG.trading_mode.value}")
    if DEFAULT_CONFIG.trading_mode == TradingMode.PAPER:
        click.echo("System is running in PAPER trading mode.")
        click.echo("No real orders will be placed.")


@main.command()
def live() -> None:
    """Attempt to enable live trading (will fail)."""
    click.echo("ERROR: Live trading is not permitted in this version of AARTA.")
    click.echo("This command always fails closed for safety.")
    raise click.ClickException(
        "Live trading is disabled. This system is paper-only until explicitly approved."
    )


@main.command()
def shadow() -> None:
    """Attempt to enable shadow trading (will fail)."""
    click.echo("ERROR: Shadow trading is not permitted in this version of AARTA.")
    click.echo("This command always fails closed for safety.")
    raise click.ClickException(
        "Shadow trading is disabled. This system is paper-only until explicitly approved."
    )


@main.command()
def live_enable() -> None:
    """Attempt to enable live trading (will fail)."""
    click.echo("ERROR: Cannot enable live trading.")
    click.echo("This command always fails closed for safety.")
    raise click.ClickException(
        "Live enable is disabled. This system is paper-only until explicitly approved."
    )


if __name__ == "__main__":
    main()
