export type ApiErrorKind =
  | "authorization"
  | "not-found"
  | "validation"
  | "unavailable"
  | "timeout"
  | "malformed-response"
  | "unexpected";

export class ApiError extends Error {
  constructor(
    public readonly kind: ApiErrorKind,
    message: string,
    public readonly status?: number,
    public readonly requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function apiErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "EOAT Atlas could not complete that request.";
}
