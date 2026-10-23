import "server-only";
import nodemailer from "nodemailer";

// Two ways out: a Gmail account with an app password (free, any recipient,
// about 500 a day) or Resend (RESEND_API_KEY + ALERT_FROM_EMAIL).
const gmail = () => Boolean(process.env.GMAIL_USER && process.env.GMAIL_APP_PASSWORD);

export const emailConfigured = () => gmail() || Boolean(process.env.RESEND_API_KEY && process.env.ALERT_FROM_EMAIL);

// Plain text twin of the HTML body: mail with only HTML looks like spam to Gmail.
const toText = (html: string) =>
  html
    .replace(/<a [^>]*href="([^"]*)"[^>]*>([^<]*)<\/a>/g, "$2: $1")
    .replace(/<\/p>\s*/g, "\n\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'")
    .trim();

// alert: the mail comes from the email alerts switch, so it says how to turn them off.
export async function sendEmail(to: string, subject: string, html: string, { alert = true } = {}) {
  const settings = `${process.env.BETTER_AUTH_URL ?? "https://flightscout-app.vercel.app"}/settings`;
  if (alert) html += `<p style="color:#888;font-size:12px">You get this because email alerts are on in FlightScout. <a href="${settings}">Turn them off in Settings</a>.</p>`;
  if (gmail()) {
    const smtp = nodemailer.createTransport({
      service: "gmail",
      auth: { user: process.env.GMAIL_USER, pass: process.env.GMAIL_APP_PASSWORD },
    });
    try {
      await smtp.sendMail({
        from: `FlightScout <${process.env.GMAIL_USER}>`,
        to,
        subject,
        html,
        text: toText(html),
        headers: alert ? { "List-Unsubscribe": `<${settings}>` } : {},
      });
      return true;
    } catch (e) {
      console.error("gmail send failed", e);
      return false;
    }
  }
  if (!emailConfigured()) return false;
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { authorization: `Bearer ${process.env.RESEND_API_KEY}`, "content-type": "application/json" },
    body: JSON.stringify({ from: process.env.ALERT_FROM_EMAIL, to, subject, html, text: toText(html) }),
    signal: AbortSignal.timeout(10_000),
  });
  return res.ok;
}
