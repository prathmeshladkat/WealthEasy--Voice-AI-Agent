"""
tools/definitions.py — the 7 tool schemas we send to Groq.

This is just a list of dicts describing what tools exist and what
parameters they accept. No logic here — just the "menu" Groq reads
to know what functions it can call.

Groq reads this list before the conversation starts and uses it to
decide mid-conversation whether to call a tool or keep generating text.

Format: OpenAI-compatible function calling schema (Groq uses the same format).
Each tool has:
  - type: always "function"
  - function.name: must exactly match the key we check in executor.py
  - function.description: what Groq reads to decide WHEN to call this tool
  - function.parameters: JSON schema describing the arguments
"""

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_portfolio_summary",
            "description": (
                "Returns all mutual funds the user currently holds, "
                "including fund name, units held, current value based on latest NAV, "
                "and amount invested. Call this when user asks about their portfolio, "
                "holdings, or overall investment summary."
            ),
            "parameters": {
                "type": "object",
                "properties": {},       # no arguments needed — user_id comes from the verified session
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_total_invested",
            "description": (
                "Returns the total amount of money the user has invested "
                "across all their mutual funds combined. "
                "Call this when user asks how much they have invested in total."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sip_deduction_dates",
            "description": (
                "Returns the day of month on which SIP is deducted for each fund, "
                "along with the SIP amount per fund. "
                "Call this when user asks when their SIP is deducted, "
                "or on which date money gets debited."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_funds_list",
            "description": (
                "Returns the list of mutual funds the user is invested in, "
                "with fund name, category, and fund house. "
                "Call this when user asks which funds they are invested in "
                "or wants to know their fund names."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_growth_rate",
            "description": (
                "Returns the overall portfolio growth — both as a percentage "
                "and as absolute rupee gain or loss. "
                "Call this when user asks about returns, growth, profit, loss, "
                "or how much their investment has grown."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_fund_detail",
            "description": (
                "Returns detailed information about one specific fund the user holds — "
                "units, current value, invested amount, SIP details. "
                "Call this when user asks about a specific fund by name, "
                "for example 'tell me about my SBI fund' or 'what about Mirae'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": (
                            "A word from the fund name or fund house the user mentioned. "
                            "Examples: 'mirae', 'sbi', 'parag', 'hdfc'. "
                            "Use lowercase, single word."
                        ),
                    }
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_sip",
            "description": (
                "Calculates the maturity value of a SIP (Systematic Investment Plan) "
                "given monthly investment amount, number of years, and optional annual return rate. "
                "Call this when user wants to know how much they will accumulate "
                "if they invest a certain amount monthly for a certain number of years. "
                "Collect monthly_amount and years from the conversation before calling. "
                "annual_rate_percent is optional — default is 12.0 percent "
                "which reflects long-term Indian equity market average."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "monthly_amount": {
                        "type": "number",
                        "description": "Monthly SIP amount in rupees. Example: 5000",
                    },
                    "years": {
                        "type": "number",
                        "description": "Number of years to invest. Example: 10",
                    },
                    "annual_rate_percent": {
                        "type": "number",
                        "description": (
                            "Expected annual return rate as a percentage. "
                            "Default is 12.0 if not specified by user. "
                            "Example: 12.0 means 12 percent per year."
                        ),
                    },
                },
                "required": ["monthly_amount", "years"],
            },
        },
    },
]