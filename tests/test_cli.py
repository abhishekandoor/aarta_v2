"""Tests for command-line interface."""

from __future__ import annotations

from click.testing import CliRunner

from aarta.cli import main


class TestHealthCommand:
    """Tests for the health command."""

    def test_health_runs(self) -> None:
        """Test that health command executes successfully."""
        runner = CliRunner()
        result = runner.invoke(main, ["health"])
        assert result.exit_code == 0
        assert "AARTA Health Check" in result.output
        assert "Trading Mode: paper" in result.output
        assert "Status: OK (Paper-Only Mode)" in result.output


class TestModeCommand:
    """Tests for the mode command."""

    def test_mode_shows_paper(self) -> None:
        """Test that mode command shows paper trading."""
        runner = CliRunner()
        result = runner.invoke(main, ["mode"])
        assert result.exit_code == 0
        assert "Current Mode: paper" in result.output
        assert "PAPER trading mode" in result.output


class TestLiveCommandRejection:
    """Tests for live-trading command rejection."""

    def test_live_command_fails(self) -> None:
        """Test that 'aarta live' fails closed."""
        runner = CliRunner()
        result = runner.invoke(main, ["live"])
        assert result.exit_code != 0
        assert (
            "Live trading is not permitted" in result.output
            or "disabled" in result.output
        )

    def test_shadow_command_fails(self) -> None:
        """Test that 'aarta shadow' fails closed."""
        runner = CliRunner()
        result = runner.invoke(main, ["shadow"])
        assert result.exit_code != 0
        assert (
            "Shadow trading is not permitted" in result.output
            or "disabled" in result.output
        )

    def test_live_enable_command_fails(self) -> None:
        """Test that 'aarta live-enable' fails closed."""
        runner = CliRunner()
        result = runner.invoke(main, ["live-enable"])
        assert result.exit_code != 0
        assert (
            "Cannot enable live trading" in result.output or "disabled" in result.output
        )


class TestVersionCommand:
    """Tests for version display."""

    def test_version_flag(self) -> None:
        """Test that --version flag works."""
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output
