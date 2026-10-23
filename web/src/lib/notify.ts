import "server-only";
import nodemailer from "nodemailer";
import type { Email } from "./email";

// Two ways out: a Gmail account with an app password (free, any recipient,
// about 500 a day) or Resend (RESEND_API_KEY + ALERT_FROM_EMAIL).
const gmail = () => Boolean(process.env.GMAIL_USER && process.env.GMAIL_APP_PASSWORD);

export const emailConfigured = () => gmail() || Boolean(process.env.RESEND_API_KEY && process.env.ALERT_FROM_EMAIL);

export async function sendEmail(to: string, { subject, html, text, unsubscribe }: Email) {
  // one click unsubscribe (RFC 8058): Gmail and Apple Mail show their own button for it
  const headers: Record<string, string> = unsubscribe
    ? { "List-Unsubscribe": `<${unsubscribe}>`, "List-Unsubscribe-Post": "List-Unsubscribe=One-Click" }
    : {};
  if (gmail()) {
    const smtp = nodemailer.createTransport({
      service: "gmail",
      auth: { user: process.env.GMAIL_USER, pass: process.env.GMAIL_APP_PASSWORD },
    });
    try {
      await smtp.sendMail({ from: `FlightScout <${process.env.GMAIL_USER}>`, to, subject, html, text, headers });
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
    body: JSON.stringify({ from: process.env.ALERT_FROM_EMAIL, to, subject, html, text, ...(unsubscribe && { headers }) }),
    signal: AbortSignal.timeout(10_000),
  });
  return res.ok;
}
