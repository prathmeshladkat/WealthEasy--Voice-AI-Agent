"""
If user asks what is todays parag parekh price we call this functions
"""


from datetime import date , datetime, timezone, timedelta
from typing import Optional
from sqlalchemy import select
from app.database import get_db_session
from app.models import NavSnapshot

IST_OFFSET = timedelta(hours=5, minutes=30)
MARKET_OPEN  = 9
MARKET_CLOSE = 16

def _get_ist_now() -> datetime:
    return datetime.now(timezone.utc) + IST_OFFSET

def get_nav_query_params() -> tuple[date,str]:
    """
    Applies the stale-NAV rule and returns (market_date, snapshot_type)
    Example:
        Called at  8:00 PM IST today  → (yesterday, 'CLOSE')
    """

    now = _get_ist_now()
    today = now.date()
    yesterday = today - timedelta(days=1)

    if MARKET_OPEN <= now.hour < MARKET_CLOSE:
        return today, "OPEN"
    else:
        return yesterday, "CLOSE"
    
async def get_nav_for_fund(fund_id: int) -> Optional[NavSnapshot]:
    """
    Returns the correct NavSnapshot for a fund based on the stale-NAV rule.
    Returns None if no snapshot exists for that date (shouldn't happen with seeded data).
    """
    market_date, snapshot_type = get_nav_query_params()

    async with get_db_session() as session:
        result = await session.execute(
            select(NavSnapshot).where(
                NavSnapshot.fund_id       == fund_id,
                NavSnapshot.market_date   == market_date,
                NavSnapshot.snapshot_type == snapshot_type,
            )
        )
        return result.scalar_one_or_none()

async def get_nav_for_multiple_funds(fund_ids: list[int]) -> dict[int, NavSnapshot]:
    """
    Returns NAV snapshots for multiple funds in one DB query.
    Returns a dict mapping fund_id → NavSnapshot.
 
    Used by get_portfolio_summary which needs NAV for ALL of a user's funds.
    One query instead of one query per fund — much faster.
 
    Example:
        navs = await get_nav_for_multiple_funds([1, 2, 3])
        navs[1].nav  # NAV for fund_id 1
        navs[2].nav  # NAV for fund_id 2
    """
    market_date, snapshot_type = get_nav_query_params()
 
    async with get_db_session() as session:
        result = await session.execute(
            select(NavSnapshot).where(
                NavSnapshot.fund_id.in_(fund_ids),       # IN (1, 2, 3) — one query for all funds
                NavSnapshot.market_date   == market_date,
                NavSnapshot.snapshot_type == snapshot_type,
            )
        )
        snapshots = result.scalars().all()
        # Convert list to dict keyed by fund_id for easy lookup
        return {snap.fund_id: snap for snap in snapshots}