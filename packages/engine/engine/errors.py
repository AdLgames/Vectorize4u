"""Error taxonomy.

The split between `BadImage` (400 class) and `TracerCrash` / `EngineError`
(500 class) is load-bearing: §3.5 of the spec requires the service to map
them to different HTTP statuses, different alerting and different retry
behaviour. Conflating them wastes days of debugging.
"""

from __future__ import annotations


class EngineError(Exception):
    """Base class. Maps to a 500 unless a subclass says otherwise."""

    error_code = "engine_error"
    http_class = 500


class BadImage(EngineError):
    """The input is the problem. Never retried, never alerted on."""

    error_code = "bad_image"
    http_class = 400


class UnsupportedFormat(BadImage):
    error_code = "unsupported_format"


class ImageTooLarge(BadImage):
    error_code = "image_too_large"


class TracerCrash(EngineError):
    """A tracer subprocess died on a signal, timed out, or produced nothing."""

    error_code = "tracer_crash"
    http_class = 500


class TracerFailed(BadImage):
    """A tracer exited non-zero with parseable stderr: the image is at fault."""

    error_code = "bad_image"
    http_class = 400


class MissingBinary(EngineError):
    error_code = "missing_binary"
