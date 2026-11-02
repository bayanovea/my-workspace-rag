class WragError(Exception):
    """An expected failure: the CLI prints the message and exits non-zero, without a traceback."""
