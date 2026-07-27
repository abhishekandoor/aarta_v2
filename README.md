# AARTA — Autonomous Adaptive Research and Trading Agent

Intraday trading research and paper-trading system.

## Overview

AARTA is an evidence-driven intraday trading research system designed for:

- Studying historical and current paper-market data
- Discovering candidate trading strategies
- Converting ideas into deterministic trading rules
- Backtesting strategies without look-ahead bias
- Detecting leakage and overfitting
- Rejecting weak or inactive strategies
- Realistically simulating orders, fills, fees and slippage
- Paper trading for one complete year
- Learning from accumulated evidence
- Comparing champion and challenger strategies
- Adapting only after rigorous validation
- Protecting capital through an independent risk authority
- Explaining every trade, rejection, failure and recovery
- Remaining safe and recoverable after crashes or corruption

## Safety First

**This system operates in PAPER-ONLY mode.**

- No broker connection
- No live trading
- No shadow trading
- No hidden live mode
- No exchange credentials
- No production API keys

All live-trading commands fail closed by design.

## Installation

```bash
uv sync
```

## Usage

### Health Check

```bash
uv run aarta health
```

### Display Trading Mode

```bash
uv run aarta mode
```

### Version

```bash
uv run aarta --version
```

### Attempted Live Commands (Always Fail)

```bash
uv run aarta live        # Fails closed
uv run aarta shadow      # Fails closed
uv run aarta live-enable # Fails closed
```

## Development

### Run Tests

```bash
uv run pytest -q
```

### Code Quality

```bash
uv run ruff check .
uv run ruff format --check .
```

## Project Structure

```
aarta/
├── src/aarta/           # Main package
│   ├── __init__.py      # Package metadata, version, trading mode flags
│   ├── cli.py           # Command-line interface
│   ├── config/          # Configuration settings
│   │   ├── __init__.py
│   │   └── settings.py  # Immutable system configuration
│   └── core/            # Core utilities
│       ├── __init__.py
│       └── logging_config.py  # UTC logging setup
├── tests/               # Test suite
├── pyproject.toml       # Project configuration
└── README.md            # This file
```

## Milestones

This project follows a 13-milestone roadmap:

1. **Foundation** — Repository structure, CLI, paper-only enforcement ✅
2. Domain and Independent Risk
3. Historical Data and Provenance
4. Event-Driven Backtesting
5. Hypothesis and Experiment System
6. Robust Evaluation and Leakage Protection
7. Realistic Paper Execution
8. Intraday Paper Runtime
9. Monitoring and User Interface
10. Regime Detection and Drift Monitoring
11. Strategy Agents and Champion/Challenger Governance
12. One-Year Paper-Trading Validation
13. Live-Readiness Assessment

## License

Copyright © AARTA Team. All rights reserved.