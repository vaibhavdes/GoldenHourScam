export type Deadline = { id: string; due_at: string; text: string };
const escape = (text: string) => text.replace(/\\/g, "\\\\").replace(/\n/g, "\\n").replace(/,/g, "\\,").replace(/;/g, "\\;");
const utc = (date: string) => new Date(date).toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
export function downloadDeadlines(caseId: string, deadlines: Deadline[]) {
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//GoldenHour//Follow-up//EN", "CALSCALE:GREGORIAN"];
  for (const d of deadlines) {
    lines.push("BEGIN:VEVENT", `UID:${caseId}-${d.id}@goldenhour`, `DTSTAMP:${utc(new Date().toISOString())}`,
      `DTSTART:${utc(d.due_at)}`, `SUMMARY:${escape("GoldenHour follow-up")}`, `DESCRIPTION:${escape(d.text)}`, "END:VEVENT");
  }
  lines.push("END:VCALENDAR");
  const url = URL.createObjectURL(new Blob([lines.join("\r\n") + "\r\n"], { type: "text/calendar;charset=utf-8" }));
  const link = document.createElement("a"); link.href = url; link.download = `${caseId}-follow-up.ics`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
