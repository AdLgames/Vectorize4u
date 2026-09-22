// Generated from the FastAPI OpenAPI schema. Do not edit by hand.
// Run `make types` (or `python packages/shared/generate.py`) after changing
// anything in apps/api/app/schemas.py.

export type AccountResponse = {
  user_id: string;
  email: string;
  plan: string;
  credits: number;
  grants: GrantResponse[];
  usage_30d: Record<string, number>;
  rate_per_minute: number;
  overage: OverageStatus;
};

export type ApiKeyCreateRequest = {
  label?: string;
};

export type ApiKeyResponse = {
  id: string;
  key_prefix: string;
  label: string;
  created_at: string;
  revoked_at: string | null;
  key: string | null;
};

export type BatchCreateRequest = {
  count: number;
  options?: JobOptions;
  webhook_url?: string | null;
  content_type?: string;
  content_length?: number;
};

export type BatchCreateResponse = {
  batch_id: string;
  slots: BatchSlot[];
  expires_in: number;
};

export type BatchFile = {
  job_id: string;
  status: string;
  error_code: string | null;
  filename: string | null;
};

export type BatchResponse = {
  id: string;
  status: string;
  total: number;
  completed: number;
  failed: number;
  files: BatchFile[];
  zip_url: string | null;
};

export type BatchSlot = {
  upload_id: string;
  put_url: string;
  headers: Record<string, string>;
};

export type BatchStartRequest = {
  upload_ids?: string[];
};

export type CheckoutRequest = {
  plan: string;
  return_to?: string | null;
};

export type CheckoutResponse = {
  checkout_url: string;
  session_id: string;
};

export type GrantResponse = {
  id: string;
  source: string;
  amount: number;
  remaining: number;
  expires_at: string | null;
};

export type JobOptions = {
  format?: ("svg" | "dxf" | "pdf" | "eps" | "png")[];
  mode?: "auto" | "flat" | "lineart" | "sketch" | "photo";
  max_colors?: number | null;
  detail?: "low" | "balanced" | "high";
  simplify?: boolean;
  keep_background?: boolean;
  despeckle?: number;
  smoothing?: number;
  alpha_mode?: "auto" | "straight" | "premultiplied";
  output_width?: number | null;
  output_height?: number | null;
  units?: "mm" | "in";
  dxf_tolerance?: number;
  min_node_spacing_mm?: number;
  quality_tier?: "fast" | "standard" | "max";
};

export type JobResponse = {
  id: string;
  status: "queued" | "processing" | "complete" | "failed" | "expired";
  kind: string;
  source_width: number | null;
  source_height: number | null;
  classification: string | null;
  classification_confidence: number | null;
  quality: Quality | null;
  physical_size: PhysicalSize | null;
  warnings: string[];
  outputs: Record<string, string>;
  preview_url: string | null;
  credits_charged: number;
  unlocked: boolean;
  error_code: string | null;
  engine_version: string | null;
  created_at: string | null;
  finished_at: string | null;
  expires_at: string | null;
};

export type OverageCapRequest = {
  opt_out: boolean;
};

export type OverageStatus = {
  allowed: boolean;
  used: number;
  cap: number;
  unit_cents: number;
  cap_opted_out: boolean;
  estimated_cents: number;
};

export type PhysicalSize = {
  width_mm: number;
  height_mm: number;
  source: "user" | "metadata" | "assumed";
};

export type PlanView = {
  id: string;
  name: string;
  kind: string;
  amount: number;
  currency: string;
  credits: number;
  description: string;
  batch_limit: number;
};

export type PortalResponse = {
  portal_url: string;
};

export type Quality = {
  total: number;
  fidelity: number;
  ssim: number;
  edge_f1: number;
  color: number;
  alpha_iou: number | null;
  nodes: number;
  paths: number;
  score_version: string;
};

export type TweakRequest = {
  options?: JobOptions;
};

export type UploadRequest = {
  content_type: string;
  content_length: number;
  filename?: string | null;
};

export type UploadResponse = {
  upload_id: string;
  put_url: string;
  method: string;
  headers: Record<string, string>;
  expires_in: number;
};

export type VectorizeRequest = {
  upload_id?: string | null;
  url?: string | null;
  options?: JobOptions;
  webhook_url?: string | null;
};
