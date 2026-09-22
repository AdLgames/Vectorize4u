"""Request/response shapes for `/v1` (§6)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Format = Literal["svg", "dxf", "pdf", "eps", "png"]


class JobOptions(BaseModel):
    """The caller-facing options of §6, validated at the edge."""

    format: list[Format] = Field(default_factory=lambda: ["svg"])  # type: ignore[arg-type]
    mode: Literal["auto", "flat", "lineart", "sketch", "photo"] = "auto"
    max_colors: int | None = Field(default=None, ge=2, le=64)
    detail: Literal["low", "balanced", "high"] = "balanced"
    simplify: bool = True
    keep_background: bool = True
    # "Clean up specks" in the UI: drops shapes smaller than roughly
    # despeckle x 3 px. Exposed because a scanned logo and a clean export
    # need very different amounts of it, and the difference is visible.
    despeckle: int = Field(default=4, ge=0, le=16)
    # "Smooth out jagged edges" in the UI. Blurs the pixel staircase before
    # tracing, so a low-resolution logo comes back as curves instead of
    # steps. Off by default: it is a deliberate trade of measured fidelity
    # for better-looking artwork, and only the customer can make it.
    smoothing: int = Field(default=0, ge=0, le=10)
    alpha_mode: Literal["auto", "straight", "premultiplied"] = "auto"
    output_width: float | None = Field(default=None, gt=0, le=10_000)
    output_height: float | None = Field(default=None, gt=0, le=10_000)
    units: Literal["mm", "in"] = "mm"
    dxf_tolerance: float = Field(default=0.1, gt=0, le=5)
    min_node_spacing_mm: float = Field(default=0.1, ge=0, le=5)
    quality_tier: Literal["fast", "standard", "max"] = "standard"

    @field_validator("format")
    @classmethod
    def _svg_always(cls, value: list[Format]) -> list[Format]:
        return list(dict.fromkeys(["svg", *value]))


def _https_url(value: str | None) -> str | None:
    """Callback URLs get the same rule as source URLs: https only.

    The full SSRF check (DNS resolved, internal addresses refused) happens
    again at delivery time, because DNS can change between the two.
    """
    if value and not value.startswith("https://"):
        raise ValueError("only https URLs are accepted")
    return value


class UploadRequest(BaseModel):
    content_type: str
    content_length: int = Field(gt=0)
    filename: str | None = None


class UploadResponse(BaseModel):
    upload_id: str
    put_url: str
    method: str = "PUT"
    headers: dict[str, str]
    expires_in: int


class VectorizeRequest(BaseModel):
    upload_id: str | None = None
    url: str | None = None
    options: JobOptions = Field(default_factory=JobOptions)
    webhook_url: str | None = None

    @field_validator("url", "webhook_url")
    @classmethod
    def _https_only(cls, value: str | None) -> str | None:
        return _https_url(value)


class TweakRequest(BaseModel):
    """The advanced panel (§7.6): one trace, as a child of the same root job."""

    options: JobOptions = Field(default_factory=JobOptions)


class Quality(BaseModel):
    total: float
    fidelity: float
    ssim: float
    edge_f1: float
    color: float
    alpha_iou: float | None = None
    nodes: int
    paths: int
    score_version: str


class PhysicalSize(BaseModel):
    width_mm: float
    height_mm: float
    source: Literal["user", "metadata", "assumed"]


class JobResponse(BaseModel):
    id: str
    status: Literal["queued", "processing", "complete", "failed", "expired"]
    kind: str
    source_width: int | None = None
    source_height: int | None = None
    classification: str | None = None
    classification_confidence: float | None = None
    quality: Quality | None = None
    physical_size: PhysicalSize | None = None
    warnings: list[str] = Field(default_factory=list)
    outputs: dict[str, str] = Field(default_factory=dict)
    preview_url: str | None = None
    credits_charged: int = 0
    unlocked: bool = False
    error_code: str | None = None
    engine_version: str | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None
    expires_at: datetime | None = None


class BatchCreateRequest(BaseModel):
    count: int = Field(gt=0, le=500)
    options: JobOptions = Field(default_factory=JobOptions)
    webhook_url: str | None = None
    content_type: str = "image/png"
    content_length: int = Field(default=25 * 1024 * 1024, gt=0)

    @field_validator("webhook_url")
    @classmethod
    def _https_only(cls, value: str | None) -> str | None:
        return _https_url(value)


class BatchSlot(BaseModel):
    upload_id: str
    put_url: str
    headers: dict[str, str]


class BatchCreateResponse(BaseModel):
    batch_id: str
    slots: list[BatchSlot]
    expires_in: int


class BatchStartRequest(BaseModel):
    upload_ids: list[str] = Field(default_factory=list)


class BatchFile(BaseModel):
    job_id: str
    status: str
    error_code: str | None = None
    filename: str | None = None


class BatchResponse(BaseModel):
    id: str
    status: str
    total: int
    completed: int
    failed: int
    files: list[BatchFile] = Field(default_factory=list)
    zip_url: str | None = None


class GrantResponse(BaseModel):
    id: str
    source: str
    amount: int
    remaining: int
    expires_at: datetime | None


class OverageStatus(BaseModel):
    allowed: bool
    used: int
    cap: int
    unit_cents: int
    cap_opted_out: bool
    #: What the overage used so far would cost, in cents.
    estimated_cents: int


class AccountResponse(BaseModel):
    user_id: str
    email: str
    plan: str
    credits: int
    grants: list[GrantResponse]
    usage_30d: dict[str, int]
    rate_per_minute: int
    overage: OverageStatus


class OverageCapRequest(BaseModel):
    #: True removes the 3x ceiling. §8 makes this explicit and deliberate:
    #: the default protects people from their own retry loops.
    opt_out: bool


class ApiKeyCreateRequest(BaseModel):
    label: str = ""


class ApiKeyResponse(BaseModel):
    id: str
    key_prefix: str
    label: str
    created_at: datetime
    revoked_at: datetime | None = None
    # Present exactly once, on creation.
    key: str | None = None


class PreviewLimits(BaseModel):
    remaining: int
    turnstile_required: bool


class EngineSummary(BaseModel):
    """What the worker hands back. Not a public shape; kept explicit so the
    API and the worker cannot drift apart silently."""

    profile: dict[str, Any]
    classification: str
    classification_confidence: float
    chosen_params: dict[str, Any]
    score: dict[str, Any]
    candidates: list[dict[str, Any]]
    warnings: list[str]
    physical_width_mm: float
    physical_size_source: str
    engine_version: str
    score_version: str
    timings_ms: dict[str, int]
    output_keys: dict[str, str]
