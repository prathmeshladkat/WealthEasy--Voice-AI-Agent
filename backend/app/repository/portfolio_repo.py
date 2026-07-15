"""
portfolio_repo.py — all database queries related to a user's portfolio.

Every function takes user_id as first argument — this is where
user scoping happens. NAV values come from nav_repo separately
and are combined in the tool executor, not here.

Why keep NAV fetching separate?
  portfolio_repo answers "what does this user hold and how much?"
  nav_repo answers "what is this fund worth today?"
  The tool executor combines both to answer "what is my portfolio value?"
  Each piece does one job — easier to test, debug, and explain.
"""

from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db_session
from app.models import Portfolio, MutualFund


async def get_user_portfolios(user_id: int) -> list[Portfolio]:
    """
    Returns all portfolio rows for a user, with the related
    MutualFund object already loaded (no second query needed).

    selectinload("fund") tells SQLAlchemy: when you fetch these
    Portfolio rows, also fetch the related MutualFund row for each
    one in the same round trip. Without this, accessing portfolio.fund
    would trigger a separate DB query per row — called N+1 problem.

    Example:
        portfolios = await get_user_portfolios(user_id=1)
        for p in portfolios:
            print(p.fund.fund_name)   # "Mirae Asset Large Cap Fund..."
            print(p.units_held)       # 800.0
            print(p.invested_amount)  # 60000.0
    """
    async with get_db_session() as session:
        result = await session.execute(
            select(Portfolio)
            .where(Portfolio.user_id == user_id)
            .options(selectinload(Portfolio.fund))  # load related MutualFund in same query
        )
        return result.scalars().all()


async def get_total_invested(user_id: int) -> float:
    """
    Returns the total amount this user has invested across all funds.
    Simple sum of invested_amount column across all their portfolios.

    Example:
        total = await get_total_invested(user_id=1)
        print(total)  # 84000.0  (60000 + 24000 for Rajesh)
    """
    from sqlalchemy import func
    async with get_db_session() as session:
        result = await session.execute(
            select(func.sum(Portfolio.invested_amount))
            .where(Portfolio.user_id == user_id)
        )
        total = result.scalar()
        return float(total) if total is not None else 0.0


async def get_sip_dates(user_id: int) -> list[dict]:
    """
    Returns each fund name + the day of month their SIP is deducted.
    Used when user asks "when is my SIP deducted?"

    Example return:
        [
            {"fund_name": "Mirae Asset Large Cap Fund...", "sip_date": 10, "sip_amount": 5000.0},
            {"fund_name": "Parag Parikh Flexi Cap Fund...", "sip_date": 5,  "sip_amount": 3000.0},
        ]
    """
    async with get_db_session() as session:
        result = await session.execute(
            select(Portfolio)
            .where(Portfolio.user_id == user_id)
            .options(selectinload(Portfolio.fund))
        )
        portfolios = result.scalars().all()
        return [
            {
                "fund_name" : p.fund.fund_name,
                "sip_date"  : p.sip_date,
                "sip_amount": float(p.sip_amount),
            }
            for p in portfolios
        ]


async def get_funds_list(user_id: int) -> list[dict]:
    """
    Returns the list of funds this user is invested in with basic details.
    Used when user asks "which funds am I invested in?"

    Example return:
        [
            {"fund_name": "Mirae Asset Large Cap Fund...", "category": "Large Cap", "amc_name": "Mirae Asset"},
            {"fund_name": "Parag Parikh Flexi Cap Fund...", "category": "Flexi Cap", "amc_name": "PPFAS"},
        ]
    """
    async with get_db_session() as session:
        result = await session.execute(
            select(Portfolio)
            .where(Portfolio.user_id == user_id)
            .options(selectinload(Portfolio.fund))
        )
        portfolios = result.scalars().all()
        return [
            {
                "fund_name": p.fund.fund_name,
                "category" : p.fund.category,
                "amc_name" : p.fund.amc_name,
            }
            for p in portfolios
        ]


async def get_fund_detail_by_keyword(user_id: int, keyword: str) -> Optional[Portfolio]:
    """
    Finds a specific fund in the user's portfolio by a keyword.
    Used when user says "tell me about my SBI fund" or "what about Mirae?"

    Searches against fund_name and amc_name (case-insensitive).
    Returns the first match, or None if no fund matches the keyword.

    Example:
        portfolio = await get_fund_detail_by_keyword(user_id=1, keyword="mirae")
        if portfolio:
            print(portfolio.fund.fund_name)  # "Mirae Asset Large Cap Fund..."
            print(portfolio.units_held)      # 800.0
    """
    async with get_db_session() as session:
        result = await session.execute(
            select(Portfolio)
            .where(Portfolio.user_id == user_id)
            .options(selectinload(Portfolio.fund))
        )
        portfolios = result.scalars().all()

        # Search in Python after loading — simpler than a LIKE query
        # and the list is small (user holds max 5-6 funds)
        keyword_lower = keyword.lower()
        for p in portfolios:
            if (keyword_lower in p.fund.fund_name.lower() or
                keyword_lower in p.fund.amc_name.lower() or
                keyword_lower in p.fund.short_name.lower()):
                return p

        return None  # no matching fund found in this user's portfolio