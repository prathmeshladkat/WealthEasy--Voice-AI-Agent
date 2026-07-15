
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from app.models import User
from app.repository import user_repo
from app.utils.number_extraction import extract_phone_number
from app.utils.pan_validation import extract_pan


class CallState(Enum):
    """
    Every call moves through these states in order.
    No skipping, no going back.
    The Enum gives us readable names instead of magic strings —
    if you typo "VERIFED" Python catches it immediately at import time.
    """
    GREETING     = "GREETING"
    VERIFY_PHONE = "VERIFY_PHONE"
    VERIFY_PAN   = "VERIFY_PAN"
    VERIFIED     = "VERIFIED"
    QUERY        = "QUERY"
    ENDING       = "ENDING"


@dataclass
class StateResult:
    """
    What the state machine returns after processing a transcript.
    The session reads this and reacts accordingly.

    Fields:
        next_state    : which state to move to after this result
        agent_message : what Aryan should say out loud (sent to TTS)
        verified_user : the User object if verification just succeeded, else None
        end_call      : True if Twilio should hang up after speaking agent_message
    """
    next_state    : CallState
    agent_message : str
    verified_user : Optional[User] = None
    end_call      : bool           = False


class VerificationStateMachine:
    """
    One instance per call. Created when the call starts, discarded when it ends.

    Usage in session.py:
        self.state_machine = VerificationStateMachine()

        # when greeting starts
        result = self.state_machine.get_greeting()

        # when a transcript arrives from Deepgram
        result = await self.state_machine.process_transcript(transcript)

        # react to result
        await self.speak(result.agent_message)
        if result.end_call:
            await self.end_call()
    """

    MAX_RETRIES = 2  # how many times user can fail before we end the call

    def __init__(self):
        self.state         : CallState    = CallState.GREETING
        self.phone_retries : int          = 0
        self.pan_retries   : int          = 0
        self.verified_phone: Optional[str] = None  # stored after phone step passes

    # ── Public methods ─────────────────────────────────────────────────────────

    def get_greeting(self) -> StateResult:
        """
        Called once when the call connects.
        Moves state from GREETING to VERIFY_PHONE and returns the opening message.
        """
        self.state = CallState.VERIFY_PHONE
        return StateResult(
            next_state    = CallState.VERIFY_PHONE,
            agent_message = (
                "Hello, thank you for calling WealthEasy. "
                "I am Aryan, your portfolio assistant. "
                "May I know your registered mobile number please?"
            ),
        )

    async def process_transcript(self, transcript: str) -> StateResult:
        """
        Main entry point. Called every time Deepgram returns a final transcript.

        Routes to the right handler based on current state.
        Only called for VERIFY_PHONE and VERIFY_PAN states —
        once we reach QUERY state, transcripts go directly to the LLM,
        not here. The session handles that routing.
        """
        if self.state == CallState.VERIFY_PHONE:
            return await self._handle_verify_phone(transcript)

        elif self.state == CallState.VERIFY_PAN:
            return await self._handle_verify_pan(transcript)

        # Should not reach here — session routes QUERY transcripts to LLM directly
        return StateResult(
            next_state    = self.state,
            agent_message = "I did not understand that. Could you please repeat?",
        )

    def set_query_state(self, user: User) -> StateResult:
        """
        Called after VERIFIED state — moves into free conversation mode.
        Returns the message Aryan speaks to open the Q&A.
        """
        self.state = CallState.QUERY
        return StateResult(
            next_state    = CallState.QUERY,
            agent_message = (
                f"Perfect, your identity has been verified. "
                f"Welcome {user.name.split()[0]}. "   # first name only — more natural in speech
                f"How can I help you with your portfolio today?"
            ),
        )

    def set_ending(self) -> StateResult:
        """Called by intent classifier when it detects the user wants to end the call."""
        self.state = CallState.ENDING
        return StateResult(
            next_state    = CallState.ENDING,
            agent_message = (
                "Thank you for calling WealthEasy. "
                "Have a great day. Goodbye."
            ),
            end_call = True,
        )


    async def _handle_verify_phone(self, transcript: str) -> StateResult:
        """
        Extracts phone number from transcript → checks DB → decides next step.

        Three possible outcomes:
          1. Valid phone found in DB   → move to VERIFY_PAN
          2. Valid phone NOT in DB     → retry or end call
          3. No valid phone extracted  → retry or end call
        """
        phone = extract_phone_number(transcript)

        if phone:
            # Phone number extracted — check if it exists in our DB
            user = await user_repo.get_user_by_phone(f"+91{phone}")  # add country code for DB lookup
            if user:
                # Phone found — store it and move to PAN verification
                self.verified_phone = f"+91{phone}"
                self.state          = CallState.VERIFY_PAN
                return StateResult(
                    next_state    = CallState.VERIFY_PAN,
                    agent_message = "Thank you. Could you please tell me your PAN card number?",
                )

        # Either no phone extracted or phone not in DB — handle retry
        self.phone_retries += 1
        if self.phone_retries >= self.MAX_RETRIES:
            self.state = CallState.ENDING
            return StateResult(
                next_state    = CallState.ENDING,
                agent_message = (
                    "I'm sorry, I was unable to verify your mobile number. "
                    "Please call us back or visit your nearest WealthEasy branch. "
                    "Thank you. Goodbye."
                ),
                end_call = True,
            )

        return StateResult(
            next_state    = CallState.VERIFY_PHONE,
            agent_message = (
                "I'm sorry, I could not find that number in our system. "
                "Could you please repeat your registered mobile number?"
            ),
        )

    async def _handle_verify_pan(self, transcript: str) -> StateResult:
        """
        Extracts PAN from transcript → checks DB against stored phone → decides next step.

        Three possible outcomes:
          1. Valid PAN that matches the stored phone → VERIFIED
          2. Valid PAN format but doesn't match phone → retry or end call
          3. No valid PAN extracted → retry or end call
        """
        pan = extract_pan(transcript)

        if pan and self.verified_phone:
            # PAN extracted — check if it matches the stored phone in DB
            user = await user_repo.get_user_by_phone_and_pan(self.verified_phone, pan)
            if user:
                # Both match — identity verified
                self.state = CallState.VERIFIED
                return StateResult(
                    next_state    = CallState.VERIFIED,
                    agent_message = (
                        f"Thank you {user.name.split()[0]}, your identity has been verified. "
                        f"How can I help you with your portfolio today?"
                    ),
                    verified_user = user,   # session attaches this user to the call
                )

        # PAN didn't match or couldn't be extracted — handle retry
        self.pan_retries += 1
        if self.pan_retries >= self.MAX_RETRIES:
            self.state = CallState.ENDING
            return StateResult(
                next_state    = CallState.ENDING,
                agent_message = (
                    "I'm sorry, I was unable to verify your PAN card number. "
                    "Please call us back or visit your nearest WealthEasy branch. "
                    "Thank you. Goodbye."
                ),
                end_call = True,
            )

        return StateResult(
            next_state    = CallState.VERIFY_PAN,
            agent_message = (
                "I'm sorry, that PAN number did not match our records. "
                "Could you please repeat your PAN card number slowly, letter by letter?"
            ),
        )