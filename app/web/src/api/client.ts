export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public fields: Record<string, string> = {},
  ) {
    super(message);
  }
}

export async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const fields: Record<string, string> = {};
    if (Array.isArray(body?.detail)) {
      for (const item of body.detail) {
        if (Array.isArray(item.loc) && typeof item.msg === "string")
          fields[String(item.loc.at(-1))] = item.msg;
      }
    }
    throw new ApiError(
      response.status,
      typeof body?.detail === "string"
        ? body.detail
        : Object.values(fields).join("; ") ||
          `Request failed (${response.status})`,
      fields,
    );
  }
  return body as T;
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return request(path, {
    method: "POST",
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
}
