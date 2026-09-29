import "server-only";

export const emailConfigured = () => Boolean(process.env.RESEND_API_KEY && process.env.ALERT_FROM_EMAIL);

export async function sendEmail(to: string, subject: string, html: string) {
  if (!emailConfigured()) return false;
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { authorization: `Bearer ${process.env.RESEND_API_KEY}`, "content-type": "application/json" },
    body: JSON.stringify({ from: process.env.ALERT_FROM_EMAIL, to, subject, html }),
    signal: AbortSignal.timeout(10_000),
  });
  return res.ok;
}
