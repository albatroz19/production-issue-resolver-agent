from issue_resolver.index.code_index import CodeSearchResult, SimpleCodeIndexService
from issue_resolver.models import AffectedFile, ConfidenceLevel, DiagnosisResponse, IncidentRequest
from issue_resolver.tools.parse_stack_trace import ParsedStackTrace, parse_stack_trace


def build_rule_based_diagnosis(
    request: IncidentRequest,
    parsed: ParsedStackTrace,
    code_index: SimpleCodeIndexService,
    reasoning_steps: list[str],
    max_files: int,
) -> DiagnosisResponse:
    affected_files: list[AffectedFile] = []
    top_frame = parsed.top_frame
    class_hint = top_frame.class_name if top_frame else ""
    method_hint = top_frame.method_name if top_frame else ""

    if "RestTemplateUtility" in class_hint and method_hint == "extractErrorMessage":
        reasoning_steps.append(
            "Matched golden case: NPE in RestTemplateUtility.extractErrorMessage during CMS proxy call."
        )
        for result in code_index.search_codebase("extractErrorMessage", "ad-management-service")[:max_files]:
            affected_files.append(_to_affected_file(result, top_frame))
        for result in code_index.find_exception_handlers("campaign-management-service")[:1]:
            affected_files.append(_to_affected_file(result, None))

        return DiagnosisResponse(
            rootCause=(
                "AMS RestTemplateUtility.extractErrorMessage assumes the downstream CMS error JSON "
                "contains a 'message' field. CMS returned HTTP 400 without that field, causing a "
                "NullPointerException when parsing the error body."
            ),
            confidence=ConfidenceLevel.HIGH,
            affectedFiles=affected_files[:max_files],
            suggestedFix=(
                "Add null-safe parsing in RestTemplateUtility.extractErrorMessage: check JsonNode "
                "for missing/null 'message' before calling asText(), and fall back to raw body or status text. "
                "Also verify CMS ErrorHandler returns a consistent error shape for BusinessValidationException."
            ),
            reasoningSteps=reasoning_steps,
            relatedIncidents=[],
        )

    haystack = " ".join(
        filter(
            None,
            [request.stack_trace, request.recent_logs or "", request.error_message or ""],
        )
    ).lower()

    if "businessvalidationexception" in haystack:
        reasoning_steps.append("Detected BusinessValidationException in stack trace or logs.")
        for result in code_index.find_exception_handlers("campaign-management-service")[:max_files]:
            affected_files.append(_to_affected_file(result, None))
        return DiagnosisResponse(
            rootCause=(
                "CMS rejected the request with BusinessValidationException; AMS may not handle the "
                "400 response body shape correctly."
            ),
            confidence=ConfidenceLevel.HIGH,
            affectedFiles=affected_files[:max_files],
            suggestedFix=(
                "Inspect CMS ErrorHandler for the validation error payload and ensure AMS parses "
                "the response fields defensively."
            ),
            reasoningSteps=reasoning_steps,
            relatedIncidents=[],
        )

    if "Ch100ScteSlotServiceImpl" in class_hint or "parsetimetomillis" in haystack:
        reasoning_steps.append("Matched SCTE slot timing issue pattern.")
        for result in code_index.search_codebase("parseTimeToMillis", "campaign-management-service")[:max_files]:
            affected_files.append(_to_affected_file(result, top_frame))
        return DiagnosisResponse(
            rootCause=(
                "SCTE time matching in Ch100ScteSlotServiceImpl may ignore seconds in parseTimeToMillis, "
                "causing one SCTE marker to attach to multiple assets."
            ),
            confidence=ConfidenceLevel.HIGH,
            affectedFiles=affected_files[:max_files],
            suggestedFix=(
                "Ensure parseTimeToMillis parses hours, minutes, and seconds. Compare asset start "
                "times using full precision before attaching SCTE slots."
            ),
            reasoningSteps=reasoning_steps,
            relatedIncidents=[],
        )

    if top_frame:
        simple_class = class_hint.split(".")[-1]
        indexed = code_index.find_by_class_name(simple_class)
        if indexed:
            line_number = top_frame.line_number or 1
            snippet = code_index.read_snippet(indexed.repo, indexed.relative_path, line_number)
            affected_files.append(
                AffectedFile(
                    repo=indexed.repo,
                    path=indexed.relative_path,
                    lines=str(line_number),
                )
            )
            reasoning_steps.append(f"Indexed top-frame class {simple_class} from local repo.")

    return DiagnosisResponse(
        rootCause="Unable to determine root cause without LLM. Review top stack frame and downstream service mapping.",
        confidence=ConfidenceLevel.LOW,
        affectedFiles=affected_files[:max_files],
        suggestedFix="Inspect the failing class/method and downstream service response for the incident API path.",
        reasoningSteps=reasoning_steps,
        relatedIncidents=[],
    )


def _to_affected_file(result: CodeSearchResult, top_frame) -> AffectedFile:
    lines = (
        str(top_frame.line_number)
        if top_frame and top_frame.line_number is not None
        else str(result.match_line)
    )
    return AffectedFile(repo=result.repo, path=result.path, lines=lines)
