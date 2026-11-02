"""
SUBSYSTEM 3: PAPER TRADING BOT & EXECUTION ENGINE
- Multi-Desk Capital Partitioning (Scalp 35%, Day 40%, Swing 25%)
- Standalone 24/7 Tick Loop (1-2s position monitoring)
- Intra-candle Target Fills, Tier-0 Breakeven Ratchets & Funding Accrual
"""

from .paper_trading_bot import PaperTradingBot

__all__ = ["PaperTradingBot"]
