class EditorError(Exception):
    """A problem we can explain to the user in plain words (shown without a traceback)."""


class Cancelled(EditorError):
    """The user cancelled a long job (render, transcription...)."""
