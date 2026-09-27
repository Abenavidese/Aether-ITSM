// FastAPI returns `detail` as a string for HTTPException, but as a list of
// {loc, msg} objects for request validation errors (422) — rendering that
// list directly shows "[object Object]".
type ValidationIssue = { msg?: string };

export function apiErrorMessage(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string' && detail) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((issue: ValidationIssue) => issue?.msg)
      .filter((msg): msg is string => typeof msg === 'string' && msg.length > 0);
    if (messages.length) return messages.join(' · ');
  }
  return fallback;
}
