from issue_resolver.tools.parse_stack_trace import parse_stack_trace


GOLDEN_STACK_TRACE = """
java.lang.NullPointerException: Cannot invoke "com.fasterxml.jackson.databind.JsonNode.asText()" because the return value is null
    at com.tataplay.admanagement.utility.RestTemplateUtility.extractErrorMessage(RestTemplateUtility.java:48)
    at com.tataplay.admanagement.utility.RestTemplateUtility.handleError(RestTemplateUtility.java:32)
Caused by: org.springframework.web.client.HttpClientErrorException$BadRequest: 400 Bad Request
""".strip()


def test_parse_stack_trace_extracts_top_frame_and_exception():
    parsed = parse_stack_trace(GOLDEN_STACK_TRACE)

    assert parsed.exception_type == "java.lang.NullPointerException"
    assert parsed.top_frame is not None
    assert "RestTemplateUtility" in parsed.top_frame.class_name
    assert parsed.top_frame.method_name == "extractErrorMessage"
    assert parsed.top_frame.line_number == 48
    assert parsed.caused_by_chain
