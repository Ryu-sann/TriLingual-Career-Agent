import logging


class RedactedErrorFilter(logging.Filter):
    """Replace exception messages: DB drivers and validation can contain private input."""

    def filter(self, record):
        if record.exc_info or record.levelno >= logging.ERROR:
            record.msg = "Operation failed; sensitive diagnostic details withheld"
            record.args = ()
            record.exc_info = None
            record.exc_text = None
        return True


def configure_logging():
    handler = logging.StreamHandler()
    handler.addFilter(RedactedErrorFilter())
    logging.basicConfig(level=logging.WARNING, handlers=[handler], force=True)
    # Dependencies may create their own handlers; keep SQL logging off in Phase 1.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.CRITICAL)
