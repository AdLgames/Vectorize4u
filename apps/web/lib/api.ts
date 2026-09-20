/**
 * The only place the web app talks to the API.
 *
 * §2: the web app is UI only — no business logic, no DB writes. Everything
 * that costs money or persists a row happens behind /v1.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export type Quality = {
  total: number;
  fidelity: number;
  ssim: number;
  edge_f1: number;
  color: number;
  alpha_iou: number | null;
  nodes: number;
  paths: number;
  /** Never compare scores across versions (§3.6). Always shown with the number. */
  score_version: string;
};

export type PhysicalSize = {
  width_mm: number;
  height_mm: number;
  source: "user" | "metadata" | "assumed";
};

export type Job = {
  id: string;
  status: "queued" | "processing" | "complete" | "failed" | "expired";
  kind: string;
  classification: string | null;
  classification_confidence: number | null;
  quality: Quality | null;
  physical_size: PhysicalSize | null;
  warnings: string[];
  /** Empty until unlock for every vector format — enforced server-side. */
  outputs: Record<string, string>;
  preview_url: string | null;
  credits_charged: number;
  unlocked: boolean;
  error_code: string | null;
  engine_version: string | null;
};

export type JobOptions = {
  format?: string[];
  mode?: "auto" | "flat" | "lineart" | "sketch" | "photo";
  max_colors?: number | null;
  detail?: "low" | "balanced" | "high";
  simplify?: boolean;
  output_width?: number | null;
  units?: "mm" | "in";
  quality_tier?: "fast" | "standard" | "max";
  dxf_tolerance?: number;
  min_node_spacing_mm?: number;
};

export type Problem = {
  error_code: string;
  detail: string;
  status: number;
  credits_remaining?: number;
};

export class ApiError extends Error {
  problem: Problem;
  constructor(problem: Problem) {
    super(problem.detail || problem.error_code);
    this.problem = problem;
  }
}

async function request<T>(
  path: string,
  init: RequestInit & { token?: string | null } = {},
): Promise<{ data: T; response: Response }> {
  const { token, headers, ...rest } = init;
  const response = await fetch(`${API_BASE}${path}`, {
    ...rest,
    headers: {
      ...(rest.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(headers ?? {}),
    },
  });

  if (!response.ok) {
    let problem: Problem = {
      error_code: "network_error",
      detail: response.statusText,
      status: response.status,
    };
    try {
      problem = { ...problem, ...(await response.json()) };
    } catch {
      /* a non-JSON error body is still an error */
    }
    throw new ApiError(problem);
  }
  return { data: (await response.json()) as T, response };
}

export async function createUpload(
  file: File,
  token?: string | null,
): Promise<{ upload_id: string; put_url: string; headers: Record<string, string> }> {
  const { data } = await request<{
    upload_id: string;
    put_url: string;
    headers: Record<string, string>;
  }>("/v1/uploads", {
    method: "POST",
    token,
    body: JSON.stringify({
      content_type: file.type || "image/png",
      content_length: file.size,
    }),
  });
  return data;
}

/**
 * Uploads never pass through the Next.js server (§4.3): the browser PUTs
 * straight to R2 with a presigned URL. Vercel caps request bodies at about
 * 4.5 MB, and a 25 MB logo is an ordinary input here.
 */
export async function putToStorage(
  putUrl: string,
  file: File,
  headers: Record<string, string>,
): Promise<void> {
  const absolute = putUrl.startsWith("http") ? putUrl : `${API_BASE}${putUrl}`;
  const response = await fetch(absolute, {
    method: "PUT",
    body: file,
    headers: { "Content-Type": headers["Content-Type"] ?? file.type },
  });
  if (!response.ok) {
    throw new ApiError({
      error_code: "upload_failed",
      detail: `storage returned ${response.status}`,
      status: response.status,
    });
  }
}

export async function startPreview(
  uploadId: string,
  options: JobOptions,
  token?: string | null,
): Promise<{ job: Job; previewsRemaining: number | null; turnstileRequired: boolean }> {
  const { data, response } = await request<Job>("/v1/preview", {
    method: "POST",
    token,
    body: JSON.stringify({ upload_id: uploadId, options }),
  });
  const remaining = response.headers.get("X-Preview-Remaining");
  return {
    job: data,
    previewsRemaining: remaining === null ? null : Number(remaining),
    turnstileRequired: response.headers.get("X-Turnstile-Required") === "1",
  };
}

export async function getJob(jobId: string, token?: string | null): Promise<Job> {
  const { data } = await request<Job>(`/v1/jobs/${jobId}`, { token });
  return data;
}

export async function tweakJob(
  jobId: string,
  options: JobOptions,
  token?: string | null,
): Promise<Job> {
  const { data } = await request<Job>(`/v1/jobs/${jobId}/tweak`, {
    method: "POST",
    token,
    body: JSON.stringify({ options }),
  });
  return data;
}

export async function unlockJob(jobId: string, token: string): Promise<Job> {
  const { data } = await request<Job>(`/v1/jobs/${jobId}/unlock`, {
    method: "POST",
    token,
  });
  return data;
}

/** Poll until terminal. The API answers 202 when a job outlives the hold window. */
export async function waitForJob(
  jobId: string,
  token?: string | null,
  { timeoutMs = 120_000 }: { timeoutMs?: number } = {},
): Promise<Job> {
  const deadline = Date.now() + timeoutMs;
  let delay = 400;
  for (;;) {
    const job = await getJob(jobId, token);
    if (job.status === "complete" || job.status === "failed" || job.status === "expired") {
      return job;
    }
    if (Date.now() > deadline) return job;
    await new Promise((resolve) => setTimeout(resolve, delay));
    delay = Math.min(delay * 1.4, 2000);
  }
}

export function tileUrl(
  jobId: string,
  { x, y, w, h, scale }: { x: number; y: number; w: number; h: number; scale: number },
): string {
  const params = new URLSearchParams({
    x: String(Math.round(x)),
    y: String(Math.round(y)),
    w: String(Math.round(w)),
    h: String(Math.round(h)),
    scale: scale.toFixed(3),
  });
  return `${API_BASE}/v1/jobs/${jobId}/preview?${params.toString()}`;
}

export type Batch = {
  id: string;
  status: string;
  total: number;
  completed: number;
  failed: number;
  files: { job_id: string; status: string; error_code: string | null }[];
  zip_url: string | null;
};

export async function createBatch(
  count: number,
  options: JobOptions,
  maxBytes: number,
  token: string,
): Promise<{ batch_id: string; slots: { upload_id: string; put_url: string; headers: Record<string, string> }[] }> {
  const { data } = await request<{
    batch_id: string;
    slots: { upload_id: string; put_url: string; headers: Record<string, string> }[];
  }>("/v1/batch", {
    method: "POST",
    token,
    body: JSON.stringify({ count, options, content_length: maxBytes }),
  });
  return data;
}

export async function startBatch(
  batchId: string,
  uploadIds: string[],
  token: string,
): Promise<Batch> {
  const { data } = await request<Batch>(`/v1/batch/${batchId}/start`, {
    method: "POST",
    token,
    body: JSON.stringify({ upload_ids: uploadIds }),
  });
  return data;
}

export async function getBatch(batchId: string, token: string): Promise<Batch> {
  const { data } = await request<Batch>(`/v1/batch/${batchId}`, { token });
  return data;
}

export async function retryBatchFile(
  batchId: string,
  jobId: string,
  token: string,
): Promise<Batch> {
  const { data } = await request<Batch>(`/v1/batch/${batchId}/retry/${jobId}`, {
    method: "POST",
    token,
  });
  return data;
}

export type Account = {
  user_id: string;
  email: string;
  plan: string;
  credits: number;
  grants: { id: string; source: string; amount: number; remaining: number; expires_at: string | null }[];
  usage_30d: { jobs: number; credits: number };
};

export async function getAccount(token: string): Promise<Account> {
  const { data } = await request<Account>("/v1/account", { token });
  return data;
}
