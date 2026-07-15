from datetime import datetime, date
from typing import Optional
from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey,
    Integer, JSON, Numeric, SmallInteger,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id            :Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name          :Mapped[str] = mapped_column(String(255), nullable=False)
    phone         :Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    pan           :Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    kyc_verified  :Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  
    created_at    :Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    portfolios: Mapped[list["Portfolio"]] = relationship("Portfolio", back_populates="user")
    call_logs : Mapped[list["CallLog"]]  = relationship("CallLog",  back_populates="user")

    def __repr__(self) -> str:
        return f"<User id={self.id} name={self.name} phone={self.phone}>"
    

class MutualFund(Base):
    __tablename__ = "mutual_funds"
 
    id         : Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fund_name  : Mapped[str] = mapped_column(String(150), nullable=False)
    short_name : Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    category   : Mapped[str] = mapped_column(String(50), nullable=False)   # Large Cap / Flexi Cap etc.
    amc_name   : Mapped[str] = mapped_column(String(100), nullable=False)  # fund house e.g. "Mirae Asset"
    isin       : Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
 
    portfolios    : Mapped[list["Portfolio"]]   = relationship("Portfolio",   back_populates="fund")
    nav_snapshots : Mapped[list["NavSnapshot"]] = relationship("NavSnapshot", back_populates="fund")
 
    def __repr__(self) -> str:
        return f"<MutualFund id={self.id} short_name={self.short_name}>"
    

class Portfolio(Base):
    __tablename__ = "portfolios"
 
    # One user holding the same fund is ONE row — enforced at DB level.
    __table_args__ = (
        UniqueConstraint("user_id", "fund_id", name="uq_portfolio_user_fund"),
    )
 
    id                : Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id           : Mapped[int]      = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    fund_id           : Mapped[int]      = mapped_column(Integer, ForeignKey("mutual_funds.id", ondelete="CASCADE"), nullable=False)
    units_held        : Mapped[float]    = mapped_column(Numeric(14, 4), nullable=False)
    avg_nav           : Mapped[float]    = mapped_column(Numeric(10, 4), nullable=False)  # average price user bought at
    sip_amount        : Mapped[float]    = mapped_column(Numeric(10, 2), nullable=False)
    sip_date          : Mapped[int]      = mapped_column(SmallInteger, nullable=False)    # day of month: 1-28
    sip_payments_made : Mapped[int]      = mapped_column(Integer, default=0, nullable=False)
    invested_amount   : Mapped[float]    = mapped_column(Numeric(12, 2), nullable=False)  # total paid in so far
    start_date        : Mapped[date]     = mapped_column(Date, nullable=False)
 
    user : Mapped["User"]       = relationship("User",       back_populates="portfolios")
    fund : Mapped["MutualFund"] = relationship("MutualFund", back_populates="portfolios")
 
    def __repr__(self) -> str:
        return f"<Portfolio user_id={self.user_id} fund_id={self.fund_id} units={self.units_held}>"
    

class NavSnapshot(Base):
    __tablename__ = "nav_snapshots"
 
    __table_args__ = (
        # Exactly one OPEN and one CLOSE per fund per day — no duplicates.
        UniqueConstraint("fund_id", "market_date", "snapshot_type", name="uq_nav_fund_date_type"),
    )
 
    id            : Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    fund_id       : Mapped[int]      = mapped_column(Integer, ForeignKey("mutual_funds.id", ondelete="CASCADE"), nullable=False)
    nav           : Mapped[float]    = mapped_column(Numeric(10, 4), nullable=False)
    snapshot_type : Mapped[str]      = mapped_column(String(5), nullable=False)   # 'OPEN' or 'CLOSE'
    market_date   : Mapped[date]     = mapped_column(Date, nullable=False)
    created_at    : Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
 
    fund: Mapped["MutualFund"] = relationship("MutualFund", back_populates="nav_snapshots")
 
    def __repr__(self) -> str:
        return f"<NavSnapshot fund_id={self.fund_id} date={self.market_date} type={self.snapshot_type} nav={self.nav}>"
    

class CallLog(Base):
    __tablename__ = "call_logs"
 
    id                     : Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_sid               : Mapped[str]            = mapped_column(String(64), unique=True, nullable=False)  # Twilio's CallSid
    user_id                : Mapped[Optional[int]]  = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    transcript             : Mapped[dict]           = mapped_column(JSON, default=list)
    outcome                : Mapped[Optional[str]]  = mapped_column(String(30), nullable=True)   # COMPLETED / VERIFICATION_FAILED / HANGUP
    verification_attempts  : Mapped[int]            = mapped_column(Integer, default=0, nullable=False)
    duration_seconds       : Mapped[Optional[int]]  = mapped_column(Integer, nullable=True)
    started_at             : Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at               : Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
 
    user: Mapped[Optional["User"]] = relationship("User", back_populates="call_logs")
 
    def __repr__(self) -> str:
        return f"<CallLog id={self.id} call_sid={self.call_sid} outcome={self.outcome}>"