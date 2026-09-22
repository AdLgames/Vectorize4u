/**
 * The content of the public API docs (§9: "Public API docs — they rank, and
 * they recruit the developer tier").
 *
 * Kept as data rather than prose-in-JSX for one reason: the API test suite
 * reads this file and fails if a documented endpoint, option or error code
 * has drifted from the live OpenAPI schema. Docs that lie are worse than no
 * docs, and API docs lie by default the moment the code moves.
 */

export type Endpoint = {
  method: "GET" | "POST" | "PUT" | "DELETE";
  path: string;
  summary: string;
  detail?: string;
};

export const ENDPOINTS: Endpoint[] = [
  {
    method: "POST",
    path: "/v1/uploads",
    summary: "Ask for a one-time upload URL",
    detail:
      "Returns {upload_id, put_url}. You PUT the bytes straight at storage, so the image never passes through the API host and there is no 4.5 MB body limit in the way.",
  },
  {
    method: "POST",
    path: "/v1/vectorize",
    summary: "Trace an uploaded image, or one at a URL",
    detail:
      "Takes {upload_id} or {url}, plus options. Holds the connection for up to 8 seconds: finished in time gives 200 with the result, otherwise 202 with the job id.",
  },
  {
    method: "POST",
    path: "/v1/vectorize/multipart",
    summary: "Trace a file posted directly",
    detail: "For small clients where `curl -F` is the whole integration.",
  },
  {
    method: "GET",
    path: "/v1/jobs/{job_id}",
    summary: "Status, scores and download URLs",
  },
  {
    method: "GET",
    path: "/v1/jobs/{job_id}/preview",
    summary: "A watermarked raster tile of the result",
    detail:
      "Takes ?x&y&w&h&scale. Rendered on the server: no vector data reaches a client before the job is paid for.",
  },
  {
    method: "POST",
    path: "/v1/jobs/{job_id}/tweak",
    summary: "Re-trace the same source with different options",
    detail:
      "A child of the same root job, so every revision of one image is covered by one charge.",
  },
  {
    method: "POST",
    path: "/v1/jobs/{job_id}/unlock",
    summary: "Spend a credit and enable the downloads",
    detail: "The web flow. API keys are charged on completion instead, so they never call this.",
  },
  {
    method: "DELETE",
    path: "/v1/jobs/{job_id}",
    summary: "Purge the source and the outputs now",
    detail: "Ahead of the retention window, for callers who would rather not wait for it.",
  },
  {
    method: "POST",
    path: "/v1/batch",
    summary: "Open a batch of up to 500 files",
    detail: "Returns an upload URL per slot.",
  },
  { method: "POST", path: "/v1/batch/{batch_id}/start", summary: "Start a batch once uploaded" },
  {
    method: "GET",
    path: "/v1/batch/{batch_id}",
    summary: "Progress, and the zip URL when it is done",
  },
  {
    method: "POST",
    path: "/v1/batch/{batch_id}/retry/{job_id}",
    summary: "Retry one failed file in a batch",
  },
  {
    method: "POST",
    path: "/v1/preview",
    summary: "A free, rate-limited trace",
    detail: "No credit is spent and no vector file is produced.",
  },
  { method: "GET", path: "/v1/account", summary: "Plan, credits by grant, usage and overage" },
  { method: "GET", path: "/v1/account/keys", summary: "List your API keys" },
  {
    method: "POST",
    path: "/v1/account/keys",
    summary: "Create a key",
    detail: "The secret is shown once, here, and never again: we store only its SHA-256 hash.",
  },
  { method: "DELETE", path: "/v1/account/keys/{key_id}", summary: "Revoke a key" },
  {
    method: "POST",
    path: "/v1/account/overage-cap",
    summary: "Opt in or out of the usage cap",
    detail:
      "The cap is on by default at three times the plan price. Removing it is a deliberate act, and it is the only way the bill goes higher.",
  },
  { method: "GET", path: "/v1/limits", summary: "Your plan's rate limit and upload ceiling" },
];

export type Option = {
  name: string;
  type: string;
  default: string;
  detail: string;
};

export const OPTIONS: Option[] = [
  {
    name: "format",
    type: "svg | dxf | pdf | eps | png",
    default: '["svg"]',
    detail: "A list. SVG is always included, because every other format is derived from it.",
  },
  {
    name: "mode",
    type: "auto | flat | lineart | sketch | photo",
    default: "auto",
    detail: "auto classifies the image first. Override it when you already know what you have.",
  },
  {
    name: "quality_tier",
    type: "fast | standard | max",
    default: "standard",
    detail: "1, 4 or 8 candidate traces. More candidates means a better pick and a longer wait.",
  },
  {
    name: "detail",
    type: "low | balanced | high",
    default: "balanced",
    detail: "How much of the image's texture to keep. high on a photo produces very large files.",
  },
  {
    name: "max_colors",
    type: "2–64",
    default: "auto",
    detail: "Caps the palette. Set it when a cutting machine has a fixed number of materials.",
  },
  {
    name: "simplify",
    type: "boolean",
    default: "true",
    detail:
      "Merges curve runs while the fidelity stays within 2% of the unsimplified trace. Off leaves every node the tracer produced.",
  },
  {
    name: "smoothing",
    type: "0\u201310",
    default: "chosen from the image",
    detail:
      "Rounds off the pixel staircase a low-resolution source leaves in the traced outline, so edges come back as curves instead of steps. Omit it and we pick a level from how much the outline turns; send 0 to switch it off. The reported score drops as the level rises, on purpose: it is measured against the steps in your file.",
  },
  {
    name: "despeckle",
    type: "0–16",
    default: "4",
    detail: "Drops specks smaller than roughly despeckle × 3 px. A scanned logo needs more.",
  },
  {
    name: "keep_background",
    type: "boolean",
    default: "true",
    detail: "Off removes the dominant background region instead of tracing it as a shape.",
  },
  {
    name: "alpha_mode",
    type: "auto | straight | premultiplied",
    default: "auto",
    detail:
      "Premultiplied alpha misread as straight is what produces dark halos around soft edges.",
  },
  {
    name: "output_width / output_height",
    type: "number",
    default: "from the image",
    detail: "Physical size, in `units`. Give one and the aspect ratio supplies the other.",
  },
  { name: "units", type: "mm | in", default: "mm", detail: "The unit for the two sizes above." },
  {
    name: "dxf_tolerance",
    type: "0–5 mm",
    default: "0.1",
    detail: "How far a DXF polyline may deviate from the curve it replaces.",
  },
  {
    name: "min_node_spacing_mm",
    type: "0–5 mm",
    default: "0.1",
    detail: "Drops nodes closer than this. Cutting software stutters on dense node runs.",
  },
];

export type ErrorCode = {
  code: string;
  status: number;
  detail: string;
};

export const ERROR_CODES: ErrorCode[] = [
  {
    code: "bad_image",
    status: 400,
    detail: "The image is the problem — corrupt, empty, or not an image. Never retried.",
  },
  { code: "unauthorized", status: 401, detail: "Missing, malformed or revoked key." },
  { code: "not_found", status: 404, detail: "No such job, batch or key — or not yours." },
  {
    code: "insufficient_credits",
    status: 402,
    detail: "Out of credits on a plan without overage. Buy credits or upgrade.",
  },
  {
    code: "overage_cap_reached",
    status: 402,
    detail:
      "The usage cap for this billing period. The body carries overage_used and overage_cap.",
  },
  {
    code: "rate_limited",
    status: 429,
    detail: "Too many requests for the plan. Retry-After says how long to wait.",
  },
  {
    code: "image_too_large",
    status: 413,
    detail: "The file is over the plan's upload ceiling.",
  },
  {
    code: "idempotency_key_reused",
    status: 409,
    detail: "An Idempotency-Key was reused with a different request body.",
  },
  {
    code: "job_not_complete",
    status: 409,
    detail: "Unlock, tweak or preview on a job that has not finished yet.",
  },
  {
    code: "source_deleted",
    status: 409,
    detail: "The retention window passed, or the source was purged. Re-upload to trace again.",
  },
  {
    code: "internal_error",
    status: 500,
    detail: "Ours. Nothing is charged, and the job can be retried.",
  },
];

export const QUICKSTART = `curl -X POST https://api.vectorize.example/v1/vectorize/multipart \\
  -H "Authorization: Bearer v4u_live_..." \\
  -F "file=@logo.png" \\
  -F 'options={"format":["svg","dxf"],"units":"mm","output_width":100}'`;

export const PRESIGNED = `# 1. ask for a slot
curl -s -X POST https://api.vectorize.example/v1/uploads \\
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \\
  -d '{"content_type":"image/png","content_length":184320}'
# → {"upload_id":"up_...","put_url":"https://..."}

# 2. put the bytes straight at storage
curl -s -X PUT "$PUT_URL" -H "Content-Type: image/png" --data-binary @logo.png

# 3. trace it
curl -s -X POST https://api.vectorize.example/v1/vectorize \\
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \\
  -H "Idempotency-Key: $(uuidgen)" \\
  -d '{"upload_id":"up_...","options":{"quality_tier":"max"}}'`;

export const WEBHOOK_VERIFY = `import hashlib, hmac

def verify(request, secret: str) -> bool:
    timestamp = request.headers["X-Vectorize-Timestamp"]
    signature = request.headers["X-Vectorize-Signature"]  # "sha256=..."
    expected = hmac.new(
        secret.encode(), timestamp.encode() + b"." + request.body, hashlib.sha256
    ).hexdigest()
    # Constant time: a fast "wrong" leaks the answer one byte at a time.
    return hmac.compare_digest(signature, f"sha256={expected}")`;
