const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface FormatSchema {
  id: string;
  bank_name: string;
  account_type: string;
  display_name: string;
  page_count: number;
  created_at: string;
  schema_json?: Record<string, unknown>;
}

export interface LearnResponse {
  id: string;
  bank_name: string;
  account_type: string;
  display_name: string;
  schema_json: Record<string, unknown>;
  page_count: number;
  created_at: string;
  updated_at: string;
}

export interface GenerateParams {
  format_id: string;
  months?: number;
  transactions_per_month?: number;
  start_date?: string;
  seed?: number;
}

export interface GenerateResponse {
  pdf_url: string;
  pages: number;
  transactions: number;
}

export interface BatchGenerateParams {
  format_id: string;
  count: number;
  months?: number;
  transactions_per_month?: number;
}

export interface BatchGenerateResponse {
  job_id: string;
  status: string;
  files: string[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const res = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "Unknown error");
    throw new ApiError(res.status, body);
  }

  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// API methods
// ---------------------------------------------------------------------------

/** Upload a PDF and learn its format. */
export async function learn(file: File): Promise<LearnResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${BASE_URL}/api/learn`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "Unknown error");
    throw new ApiError(res.status, body);
  }

  return res.json() as Promise<LearnResponse>;
}

/** List all learned formats. */
export async function getFormats(): Promise<FormatSchema[]> {
  return request<FormatSchema[]>("/api/formats");
}

/** Get a single format by ID. */
export async function getFormat(id: string): Promise<FormatSchema> {
  return request<FormatSchema>(`/api/formats/${id}`);
}

/** Delete a format by ID. */
export async function deleteFormat(id: string): Promise<void> {
  await request<void>(`/api/formats/${id}`, { method: "DELETE" });
}

/** Generate a single synthetic PDF. */
export async function generate(
  params: GenerateParams,
): Promise<GenerateResponse> {
  return request<GenerateResponse>("/api/generate", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

/** Generate a preview (single page, watermarked). */
export async function generatePreview(
  params: GenerateParams,
): Promise<GenerateResponse> {
  return request<GenerateResponse>("/api/generate/preview", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

/** Start a batch generation job. */
export async function generateBatch(
  params: BatchGenerateParams,
): Promise<BatchGenerateResponse> {
  return request<BatchGenerateResponse>("/api/generate/batch", {
    method: "POST",
    body: JSON.stringify(params),
  });
}
