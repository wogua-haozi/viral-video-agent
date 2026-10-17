"""Per-attempt ASR consumption shared by Worker child tasks and tool calls."""

import math
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class ASRUsageState:
    asr_seconds: float = 0
    receipts: set[str] = field(default_factory=set)


_asr_usage_state: ContextVar[ASRUsageState | None] = ContextVar("asr_usage_state", default=None)


class ASRUsageTracker:
    def reset(self) -> ASRUsageState:
        # Initialize before creating child tasks: copied contexts then share
        # this state, while each new Worker attempt receives its own state.
        state = ASRUsageState()
        _asr_usage_state.set(state)
        return state

    def record(self, result: object) -> None:
        """Accept completed-call receipts, including remote MCP responses.

        Recording must not throw or trigger a paid local fallback when the
        remote tool already succeeded. Legacy responses without a receipt are
        unmeasured; their audio duration is not evidence of a new ASR call.
        """
        state = _asr_usage_state.get()
        if state is None:
            return
        for item in result if isinstance(result, list) else [result]:
            if not isinstance(item, dict):
                continue
            receipt = item.get("asr_usage_receipt")
            if not isinstance(receipt, dict):
                continue
            receipt_id = receipt.get("id")
            seconds = receipt.get("seconds")
            if not isinstance(receipt_id, str) or not receipt_id or isinstance(seconds, bool):
                continue
            try:
                seconds = float(seconds)
            except (TypeError, ValueError, OverflowError):
                continue
            if not math.isfinite(seconds) or seconds <= 0 or receipt_id in state.receipts:
                continue
            state.receipts.add(receipt_id)
            state.asr_seconds += seconds


asr_usage_tracker = ASRUsageTracker()
