from dataclasses import dataclass, field
import re
from typing import List, Optional


FRAME_PATTERN = re.compile(
    r"at\s+([\w.$]+)\.([\w$]+)\(([^:)]+)(?::(\d+))?\)"
)
EXCEPTION_PATTERN = re.compile(r"^([\w.$]+(?:Exception|Error)):\s*(.*)$")


@dataclass
class StackFrame:
    class_name: str
    method_name: str
    file_name: str
    line_number: Optional[int] = None


@dataclass
class ParsedStackTrace:
    exception_type: Optional[str] = None
    exception_message: Optional[str] = None
    top_frame: Optional[StackFrame] = None
    frames: List[StackFrame] = field(default_factory=list)
    caused_by_chain: List[str] = field(default_factory=list)


def parse_stack_trace(stack_trace: str | None) -> ParsedStackTrace:
    if not stack_trace or not stack_trace.strip():
        return ParsedStackTrace()

    lines = [line.strip() for line in stack_trace.splitlines() if line.strip()]
    frames: List[StackFrame] = []
    caused_by_chain: List[str] = []
    exception_type: Optional[str] = None
    exception_message: Optional[str] = None

    for line in lines:
        frame_match = FRAME_PATTERN.search(line)
        if frame_match:
            frames.append(
                StackFrame(
                    class_name=frame_match.group(1),
                    method_name=frame_match.group(2),
                    file_name=frame_match.group(3),
                    line_number=int(frame_match.group(4)) if frame_match.group(4) else None,
                )
            )
            continue

        exception_match = EXCEPTION_PATTERN.match(line)
        if exception_match and exception_type is None:
            exception_type = exception_match.group(1)
            exception_message = exception_match.group(2)
            continue

        if line.startswith("Caused by:"):
            caused_by_chain.append(line[len("Caused by:") :].strip())

    if exception_type is None and lines:
        first_line = lines[0]
        colon_index = first_line.find(":")
        if colon_index > 0:
            exception_type = first_line[:colon_index].strip()
            exception_message = first_line[colon_index + 1 :].strip()
        else:
            exception_type = first_line

    return ParsedStackTrace(
        exception_type=exception_type,
        exception_message=exception_message,
        top_frame=frames[0] if frames else None,
        frames=frames,
        caused_by_chain=caused_by_chain,
    )


def format_parsed_stack_trace(parsed: ParsedStackTrace) -> str:
    lines = [
        f"exceptionType: {parsed.exception_type}",
        f"exceptionMessage: {parsed.exception_message}",
    ]
    if parsed.top_frame:
        frame = parsed.top_frame
        location = f"{frame.class_name}.{frame.method_name}({frame.file_name}"
        if frame.line_number is not None:
            location += f":{frame.line_number}"
        location += ")"
        lines.append(f"topFrame: {location}")
    if parsed.caused_by_chain:
        lines.append(f"causedByChain: {parsed.caused_by_chain}")
    return "\n".join(lines)
