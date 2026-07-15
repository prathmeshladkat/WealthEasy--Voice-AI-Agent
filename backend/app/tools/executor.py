import math
from typing import Any 
from app.cache import get_cached, set_cached
from app.repository import nav_repo, portfolio_repo
from app.utils.logger import logger

async def execute_tool(tool_name: str, args: dict, user_id: int) -> dict[str, Any]:
    logger.info(f"Executing tool: {tool_name} args={args} user_id={user_id}")
async def execute_tool(tool_name: str, args: dict, user_id: int) -> dict[str, Any]:
    # Route to the right handler
    if tool_name == "get_portfolio_summary":
        return await _get_portfolio_summary(user_id)
 
    elif tool_name == "get_total_invested":
        return await _get_total_invested(user_id)
 
    elif tool_name == "get_sip_deduction_dates":
        return await _get_sip_deduction_dates(user_id)
 
    elif tool_name == "get_funds_list":
        return await _get_funds_list(user_id)
 
    elif tool_name == "get_growth_rate":
        return await _get_growth_rate(user_id)
 
    elif tool_name == "get_fund_detail":
        keyword = args.get("keyword", "").lower().strip()
        return await _get_fund_detail(user_id, keyword)
 
    elif tool_name == "calculate_sip":
        monthly_amount      = float(args.get("monthly_amount", 0))
        years               = float(args.get("years", 0))
        annual_rate_percent = float(args.get("annual_rate_percent", 12.0))
        return _calculate_sip(monthly_amount, years, annual_rate_percent)
 
    else:
        return {"error": f"Unknown tool: {tool_name}"}


async def _get_portfolio_summary(user_id: int) -> dict:
    # Check cache first
    cached = await get_cached(user_id, "get_portfolio_summary")
    if cached:
        return cached
 
    # Cache miss — fetch from DB
    portfolios = await portfolio_repo.get_user_portfolios(user_id)
    if not portfolios:
        return {"error": "No portfolio found for this user."}
 
    # Get NAV for all funds in one query
    fund_ids = [p.fund_id for p in portfolios]
    navs     = await nav_repo.get_nav_for_multiple_funds(fund_ids)
 
    # Get the NAV date/type so we can tell the user which NAV we used
    nav_date, nav_type = nav_repo.get_nav_query_params()
 
    funds_detail = []
    total_current_value = 0.0
    total_invested      = 0.0
 
    for p in portfolios:
        nav_snapshot  = navs.get(p.fund_id)
        current_nav   = float(nav_snapshot.nav) if nav_snapshot else float(p.avg_nav)
        current_value = float(p.units_held) * current_nav
 
        total_current_value += current_value
        total_invested      += float(p.invested_amount)
 
        funds_detail.append({
            "fund_name"    : p.fund.fund_name,
            "units_held"   : float(p.units_held),
            "current_nav"  : current_nav,
            "current_value": round(current_value, 2),
            "invested"     : float(p.invested_amount),
        })
 
    result = {
        "funds"              : funds_detail,
        "total_current_value": round(total_current_value, 2),
        "total_invested"     : round(total_invested, 2),
        "nav_date"           : str(nav_date),
        "nav_type"           : nav_type,
    }
 
    await set_cached(user_id, "get_portfolio_summary", result)
    return result
 
 
async def _get_total_invested(user_id: int) -> dict:
    cached = await get_cached(user_id, "get_total_invested")
    if cached:
        return cached
 
    total = await portfolio_repo.get_total_invested(user_id)
    result = {"total_invested": round(total, 2)}
 
    await set_cached(user_id, "get_total_invested", result)
    return result
 
 
async def _get_sip_deduction_dates(user_id: int) -> dict:
    cached = await get_cached(user_id, "get_sip_deduction_dates")
    if cached:
        return cached
 
    sip_dates = await portfolio_repo.get_sip_dates(user_id)
    result    = {"sip_details": sip_dates}
 
    await set_cached(user_id, "get_sip_deduction_dates", result)
    return result
 
 
async def _get_funds_list(user_id: int) -> dict:
    cached = await get_cached(user_id, "get_funds_list")
    if cached:
        return cached
 
    funds  = await portfolio_repo.get_funds_list(user_id)
    result = {"funds": funds}
 
    await set_cached(user_id, "get_funds_list", result)
    return result
 
 
async def _get_growth_rate(user_id: int) -> dict:
    cached = await get_cached(user_id, "get_growth_rate")
    if cached:
        return cached
 
    # Reuse portfolio summary data to avoid duplicate DB calls
    # If portfolio summary is already cached this is essentially free
    summary = await _get_portfolio_summary(user_id)
 
    if "error" in summary:
        return summary
 
    total_invested      = summary["total_invested"]
    total_current_value = summary["total_current_value"]
    absolute_gain       = round(total_current_value - total_invested, 2)
 
    # Simple growth percentage — not XIRR but good enough for a demo
    # Formula: ((current - invested) / invested) * 100
    growth_percent = round((absolute_gain / total_invested) * 100, 2) if total_invested > 0 else 0.0
 
    result = {
        "total_invested"     : total_invested,
        "total_current_value": total_current_value,
        "absolute_gain"      : absolute_gain,
        "growth_percent"     : growth_percent,
        "nav_date"           : summary["nav_date"],
        "nav_type"           : summary["nav_type"],
    }
 
    await set_cached(user_id, "get_growth_rate", result)
    return result
 
 
async def _get_fund_detail(user_id: int, keyword: str) -> dict:
    # Cache key includes the keyword so "mirae" and "sbi" are separate slots
    cached = await get_cached(user_id, "get_fund_detail", args_signature=keyword)
    if cached:
        return cached
 
    portfolio = await portfolio_repo.get_fund_detail_by_keyword(user_id, keyword)
    if not portfolio:
        return {"error": f"No fund matching '{keyword}' found in your portfolio."}
 
    nav_snapshot = await nav_repo.get_nav_for_fund(portfolio.fund_id)
    nav_date, nav_type = nav_repo.get_nav_query_params()
 
    current_nav   = float(nav_snapshot.nav) if nav_snapshot else float(portfolio.avg_nav)
    current_value = round(float(portfolio.units_held) * current_nav, 2)
    gain          = round(current_value - float(portfolio.invested_amount), 2)
 
    result = {
        "fund_name"    : portfolio.fund.fund_name,
        "category"     : portfolio.fund.category,
        "amc_name"     : portfolio.fund.amc_name,
        "units_held"   : float(portfolio.units_held),
        "avg_nav"      : float(portfolio.avg_nav),
        "current_nav"  : current_nav,
        "current_value": current_value,
        "invested"     : float(portfolio.invested_amount),
        "gain"         : gain,
        "sip_amount"   : float(portfolio.sip_amount),
        "sip_date"     : portfolio.sip_date,
        "nav_date"     : str(nav_date),
        "nav_type"     : nav_type,
    }
 
    await set_cached(user_id, "get_fund_detail", result, args_signature=keyword)
    return result
 
 
def _calculate_sip(monthly_amount: float, years: float, annual_rate_percent: float) -> dict:
    """
    Standard SIP future value formula:
        FV = P × [((1 + r)^n - 1) / r] × (1 + r)
 
    Where:
        P = monthly_amount
        r = monthly rate = annual_rate / 12 / 100
        n = total months = years × 12
 
    No cache — user can change inputs mid-conversation.
    No DB — pure math.
    """
    # Edge case: if rate is 0 just return simple multiplication
    if annual_rate_percent <= 0:
        total_invested  = monthly_amount * years * 12
        return {
            "monthly_amount"     : monthly_amount,
            "years"              : years,
            "annual_rate_percent": annual_rate_percent,
            "total_invested"     : round(total_invested, 2),
            "maturity_value"     : round(total_invested, 2),
            "total_gain"         : 0.0,
        }
 
    r = annual_rate_percent / 12 / 100   # monthly interest rate
    n = years * 12                        # total number of months
 
    maturity_value = monthly_amount * (((1 + r) ** n - 1) / r) * (1 + r)
    total_invested = monthly_amount * n
    total_gain     = maturity_value - total_invested
 
    return {
        "monthly_amount"     : monthly_amount,
        "years"              : years,
        "annual_rate_percent": annual_rate_percent,
        "total_invested"     : round(total_invested, 2),
        "maturity_value"     : round(maturity_value, 2),
        "total_gain"         : round(total_gain, 2),
    }