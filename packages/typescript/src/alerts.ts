import { SessionTelemetry } from "./types";

export interface AlertOptions {
  slackWebhookUrl?: string;
  telegramBotToken?: string;
  telegramChatId?: string;
  genericWebhookUrl?: string;
}

export class AlertDispatcher {
  options: AlertOptions;

  constructor(options: AlertOptions = {}) {
    this.options = options;
  }

  notifyTrip(session: SessionTelemetry, tripDetails: Record<string, any>) {
    // Fire and forget, no await to avoid blocking event loop
    this.sendAll(session, tripDetails).catch((err) => {
      console.warn("[Loop-Guard Alert] Dispatch error:", err.message);
    });
  }

  async sendAll(session: SessionTelemetry, tripDetails: Record<string, any>) {
    const promises: Promise<any>[] = [];
    if (this.options.slackWebhookUrl) {
      promises.push(this.sendSlack(session, tripDetails));
    }
    if (this.options.telegramBotToken && this.options.telegramChatId) {
      promises.push(this.sendTelegram(session, tripDetails));
    }
    if (this.options.genericWebhookUrl) {
      promises.push(this.sendGeneric(session, tripDetails));
    }
    await Promise.allSettled(promises);
  }

  async sendSlack(session: SessionTelemetry, tripDetails: Record<string, any>) {
    const payload = {
      blocks: [
        {
          type: "header",
          text: {
            type: "plain_text",
            text: "🚨 Loop-Guard Alert: Circuit Tripped!",
            emoji: true,
          },
        },
        {
          type: "section",
          text: {
            type: "mrkdwn",
            text:
              `*Reason:* \`${tripDetails.reason || session.tripReason}\`\n` +
              `*Session ID:* \`${session.sessionId}\`\n` +
              `*Tool:* \`${tripDetails.toolName || "N/A"}\`\n` +
              `*Depth:* \`${session.currentDepth}\` steps\n` +
              `*Cost Incurred:* \`$${session.budget.totalCostUsd.toFixed(4)}\`\n` +
              `*Status:* Execution halted safely to save tokens.`,
          },
        },
        {
          type: "context",
          elements: [
            {
              type: "mrkdwn",
              text: "🛡️ *Protected by RunLog Loop-Guard (runlog.cc)*",
            },
          ],
        },
      ],
    };

    await fetch(this.options.slackWebhookUrl!, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  async sendTelegram(session: SessionTelemetry, tripDetails: Record<string, any>) {
    const text =
      `🚨 <b>Loop-Guard: Circuit Breaker Tripped!</b>\n\n` +
      `• <b>Reason:</b> <code>${tripDetails.reason || session.tripReason}</code>\n` +
      `• <b>Session:</b> <code>${session.sessionId}</code>\n` +
      `• <b>Tool:</b> <code>${tripDetails.toolName || "N/A"}</code>\n` +
      `• <b>Cost:</b> <code>$${session.budget.totalCostUsd.toFixed(4)}</code>\n\n` +
      `<i>Execution halted safely to save tokens.</i>`;

    const url = `https://api.telegram.org/bot${this.options.telegramBotToken}/sendMessage`;
    await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: this.options.telegramChatId,
        text,
        parse_mode: "HTML",
      }),
    });
  }

  async sendGeneric(session: SessionTelemetry, tripDetails: Record<string, any>) {
    await fetch(this.options.genericWebhookUrl!, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        event: "circuit_breaker.tripped",
        session,
        tripDetails,
      }),
    });
  }
}
