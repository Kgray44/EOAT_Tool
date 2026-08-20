/** Format an ISO-8601 instant in the user's local timezone by default. */
export function formatTime(value: string, timeZone?: string) {
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
    timeZone,
  }).format(new Date(value));
}
