import logging

from career_agent.core.security import RedactedErrorFilter


def test_error_redacts_message_args_and_exception():
    record = logging.LogRecord(
        "test",
        logging.ERROR,
        "test",
        1,
        "private connection: %s",
        ("sensitive-value",),
        (ValueError, ValueError("private-input"), None),
    )
    assert RedactedErrorFilter().filter(record)
    assert "sensitive-value" not in record.getMessage()
    assert "private connection" not in record.getMessage()
    assert record.exc_info is None
    assert record.exc_text is None
