export function fmtMoney(n: number) {
  return "£" + n.toLocaleString();
}

// Backend stores UTC datetimes but may omit the 'Z' suffix on some fields.
// Without a timezone marker JS Date() interprets the string as LOCAL time,
// shifting the displayed time by the browser's UTC offset. Appending 'Z'
// forces UTC interpretation for any naive ISO string.
function toUtc(iso: string): Date {
  if (iso && !iso.endsWith("Z") && !/[+-]\d{2}:\d{2}$/.test(iso)) {
    return new Date(iso + "Z");
  }
  return new Date(iso);
}

export function fmtRelative(iso: string) {
  const diff = Date.now() - toUtc(iso).getTime();
  const m = Math.round(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  return `${d}d ago`;
}
export function fmtDateTime(iso: string): string {
  if (!iso) return "-";
  const d = toUtc(iso);
  if (isNaN(d.getTime())) return "-";
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/London",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(d);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("day")}/${get("month")}/${get("year")} ${get("hour")}:${get("minute")}`;
}

export function fmtDate(iso: string): string {
  if (!iso) return "-";
  const d = toUtc(iso);
  if (isNaN(d.getTime())) return "-";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/London",
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(d);
}
