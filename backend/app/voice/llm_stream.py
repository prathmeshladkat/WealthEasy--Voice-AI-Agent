"""
voice/llm_stream.py — Groq streaming with tool calling support.

Clean rewrite fixing two bugs from v1:
  1. finish_reason check moved OUTSIDE the chunk loop — only the last
     chunk has a non-None finish_reason, so we collect all chunks first
     then decide what happened
  2. tool_args_str "null" handled — Groq sends "null" for tools with
     no arguments, json.loads("null") returns None so we default to {}
"""

import json
from typing import Callable, Awaitable

from groq import AsyncGroq

from app.config import settings
from app.tools.definitions import TOOL_DEFINITIONS
from app.tools.executor import execute_tool
from app.utils.logger import logger
from app.utils.number_to_words import format_rupees_spoken, format_number_spoken


# Key names (substring match, case-insensitive) that indicate a field holds a
# rupee amount rather than a plain count/percentage/year. Used to decide
# whether a "_spoken" field gets "rupees" appended or not.
_MONEY_KEY_HINTS = (
    "amount", "value", "invested", "gain", "worth", "balance",
    "nav", "maturity", "rupee", "portfolio", "price", "cost", "total",
)


def _looks_like_money(key: str) -> bool:
    key_lower = key.lower()
    return any(hint in key_lower for hint in _MONEY_KEY_HINTS)


def _add_spoken_fields(data):
    """
    Walks a tool result (dicts / lists of dicts) and adds a "<key>_spoken"
    sibling for every numeric value, pre-formatted deterministically in
    Python — NOT left for the LLM to convert freely.

    Why: we confirmed in production that the LLM can receive a fully correct
    number (e.g. monthly_amount: 5000) and still speak it wrong (e.g. "fifty
    thousand rupees"). The fix is to remove that free-form conversion step
    entirely for anything we can pre-format ourselves; the model is
    instructed (see SYSTEM_PROMPT) to relay "_spoken" values verbatim rather
    than recompute them from the raw number.
    """
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            result[key] = value
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if _looks_like_money(key):
                    result[f"{key}_spoken"] = format_rupees_spoken(value)
                else:
                    result[f"{key}_spoken"] = format_number_spoken(value)
            elif isinstance(value, (dict, list)):
                result[key] = _add_spoken_fields(value)
        return result
    elif isinstance(data, list):
        return [_add_spoken_fields(item) for item in data]
    return data


SENTENCE_ENDINGS = {".", "?", "!"}

SYSTEM_PROMPT = """
You are Aryan, a portfolio assistant at WealthEasy, an Indian mutual fund company.

IDENTITY:
- You are professional, warm, and concise like a real relationship manager
- Never reveal you are an AI unless directly asked
- Address the user by their first name when you know it

SPEECH RULES (critical — this is a voice call, not text):
- Maximum 2 to 3 sentences per response
- Never use markdown, bullet points, symbols, or formatting of any kind
- Never say rupee symbol — always say "rupees"

NUMBERS — CRITICAL, READ CAREFULLY:
- Tool results include a "<field>_spoken" version next to every number
  (e.g. "monthly_amount": 5000, "monthly_amount_spoken": "five thousand rupees")
- You MUST use the "_spoken" text EXACTLY as given whenever you say that number out loud
- Do NOT recompute, reword, or re-derive the number yourself from the raw digits —
  the "_spoken" field is already correct and verified; retyping it in your own words
  risks getting the magnitude wrong (e.g. confusing thousand/lakh)
- If a number has no matching "_spoken" field, then speak it naturally as a fallback
  (e.g. "twelve percent" not "12%", "tenth of July" not "10/07")

NAV POLICY:
- Always tell the user which NAV you are using and its date
- Example: "This is based on the closing NAV as of yesterday"

AFTER ANSWERING:
- You MUST speak the actual data from the tool result first
- Then ask "Is there anything else I can help you with?"
- Never skip straight to asking if there is anything else
- Example: "Your portfolio is worth eighty four thousand rupees. Is there anything else I can help you with?"

SIP CALCULATOR:
- If user asks to calculate SIP returns, first ask for monthly amount if not given
- Then ask for number of years if not given
- Then ask if they want to use the default twelve percent annual return or specify their own
- Only call calculate_sip once you have all inputs
""".strip()


async def stream_llm_response(
    messages      : list[dict],
    user_id       : int,
    on_sentence   : Callable[[str], Awaitable[None]],
    on_tool_start : Callable[[str], Awaitable[None]],
    
) -> list[dict]:
    """
    Streams a Groq response handling both text tokens and tool calls.
    Loops until Groq returns a final text response (finish_reason == stop).
    """
    client   = AsyncGroq(api_key=settings.GROQ_API_KEY)
    messages = list(messages)

    while True:
        # ── Accumulators reset each iteration ─────────────────────────────────
        text_buffer   = ""
        full_text     = ""
        tool_name     = ""
        tool_args_str = ""
        tool_call_id  = ""
        finish_reason = None   # will be set by the LAST chunk only

        stream = await client.chat.completions.create(
            model       = settings.GROQ_MODEL,
            messages    = messages,
            tools       = TOOL_DEFINITIONS,
            tool_choice = "auto",
            stream      = True,
            max_tokens  = 300,
            temperature = 0.7,
        )

        # ── Collect all chunks ─────────────────────────────────────────────────
        # finish_reason is only non-None on the LAST chunk.
        # We process text tokens as they arrive (for low latency TTS)
        # but wait until the stream ends to act on finish_reason.
        async for chunk in stream:
            choice = chunk.choices[0]
            delta  = choice.delta

            # ── Text token ────────────────────────────────────────────────────
            if delta.content:
                text_buffer += delta.content

                # Send complete sentences to TTS as they form
                while True:
                    boundary = _find_sentence_boundary(text_buffer)
                    if boundary == -1:
                        break
                    sentence    = text_buffer[:boundary + 1].strip()
                    text_buffer = text_buffer[boundary + 1:].strip()
                    if sentence:
                        full_text += sentence + " "
                        await on_sentence(sentence)

            # ── Tool call chunk ───────────────────────────────────────────────
            elif delta.tool_calls:
                tc = delta.tool_calls[0]
                if tc.id:
                    tool_call_id = tc.id
                if tc.function.name:
                    tool_name += tc.function.name
                if tc.function.arguments:
                    tool_args_str += tc.function.arguments

            # ── Capture finish_reason (only set on last chunk) ────────────────
            if choice.finish_reason is not None:
                finish_reason = choice.finish_reason

        # ── After stream ends, act on finish_reason ────────────────────────────
        logger.info(f"Stream ended with finish_reason={finish_reason}")

        if finish_reason == "tool_calls":
            # Parse tool arguments — handle "null" string from Groq
            try:
                tool_args = json.loads(tool_args_str) if tool_args_str else {}
                if tool_args is None:
                    tool_args = {}
            except json.JSONDecodeError:
                tool_args = {}

            logger.info(f"Executing tool: {tool_name} args={tool_args}")
            await on_tool_start(tool_name)

            tool_result = await execute_tool(tool_name, tool_args, user_id)
            logger.info(f"Tool result received: {list(tool_result.keys()) if tool_result else 'empty'}")

            # Deterministically pre-format every number in the result as spoken
            # words BEFORE the model ever sees it — see _add_spoken_fields docstring.
            tool_result = _add_spoken_fields(tool_result)

            # Inject tool call + result into message history
            messages.append({
                "role"      : "assistant",
                "tool_calls": [{
                    "id"      : tool_call_id,
                    "type"    : "function",
                    "function": {
                        "name"     : tool_name,
                        "arguments": tool_args_str or "{}",
                    },
                }],
            })
            messages.append({
                "role"        : "tool",
                "tool_call_id": tool_call_id,
                "content"     : json.dumps(tool_result),
            })

            messages.append({
                "role"   : "user",
                "content": "Please summarize this information for me in simple spoken words.",
            })
            # Loop again — Groq will now generate the spoken response

        elif finish_reason == "stop":
            # Flush any remaining text in buffer
            if text_buffer.strip():
                full_text += text_buffer.strip()
                await on_sentence(text_buffer.strip())

            # Append complete assistant response to history
            messages.append({
                "role"   : "assistant",
                "content": full_text.strip(),
            })
            logger.info(f"LLM response complete: '{full_text.strip()[:80]}'")
            return messages

        else:
            # Unexpected finish_reason — log and exit loop safely
            logger.warning(f"Unexpected finish_reason: {finish_reason}")
            break

    return messages


def _find_sentence_boundary(text: str) -> int:
    """
    Returns index of first sentence-ending punctuation followed by
    a space or end of string. Returns -1 if no boundary found.
    """
    for i, char in enumerate(text):
        if char in SENTENCE_ENDINGS:
            if i == len(text) - 1 or text[i + 1] == " ":
                return i
    return -1


def build_initial_messages(user_name: str | None = None) -> list[dict]:
    """
    Returns starting messages list for a new verified session.

    user_name: the verified caller's actual first name (from user_repo lookup
    during VERIFY_PAN). Without this, the SYSTEM_PROMPT's instruction to
    "address the user by their first name when you know it" has nothing to
    draw on — the model would otherwise invent a plausible-sounding name
    (confirmed in production: it fabricated "Rohan" for a caller actually
    named "Priya Sharma"). Passing the real name here closes that gap.
    """
    system_content = SYSTEM_PROMPT
    if user_name:
        system_content += (
            f"\n\nCALLER IDENTITY:\n"
            f"- The verified caller's first name is {user_name}.\n"
            f"- Use this exact name when addressing them or closing the call. "
            f"Do not use any other name."
        )
    return [{"role": "system", "content": system_content}]


def add_user_message(messages: list[dict], text: str) -> list[dict]:
    """Appends a user message to conversation history."""
    return messages + [{"role": "user", "content": text}]