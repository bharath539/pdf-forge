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
  version?: string;
  data_field_count?: number;
  schema_json?: Record<string, unknown>;
  template_json?: Record<string, unknown>;
}

export interface LearnResponse {
  id: string;
  bank_name: string;
  account_type: string;
  display_name: string;
  page_count: number;
  data_field_count?: number;
  template_json?: Record<string, unknown>;
  schema_json?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface GenerateParams {
  schema_id: string;
  scenario?: string;
  start_date?: string;
  months?: number;
  transactions_per_month?: { min: number; max: number };
  opening_balance?: string;
  include_edge_cases?: boolean;
  seed?: number | null;
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

/** Generate a single synthetic PDF. Returns a Blob. */
export async function generate(params: GenerateParams): Promise<Blob> {
  const res = await fetch(`${BASE_URL}/api/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "Unknown error");
    throw new ApiError(res.status, body);
  }
  return res.blob();
}

/** Generate a preview (first page only). Returns a Blob. */
export async function generatePreview(params: GenerateParams): Promise<Blob> {
  const res = await fetch(`${BASE_URL}/api/generate/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "Unknown error");
    throw new ApiError(res.status, body);
  }
  return res.blob();
}

/** Generate multiple scenario PDFs as a zip. Returns a Blob. */
export async function generateBatch(params: {
  schema_id: string;
  scenarios: string[];
  start_date?: string;
  seed?: number | null;
}): Promise<Blob> {
  const res = await fetch(`${BASE_URL}/api/generate/batch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "Unknown error");
    throw new ApiError(res.status, body);
  }
  return res.blob();
}
