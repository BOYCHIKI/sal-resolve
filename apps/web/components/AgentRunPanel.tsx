"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { startAgentRun } from "@/app/actions";
import { AutoRefresh } from "@/components/AutoRefresh";
import { Working } from "@/components/Working";
import type { AgentRun, AgentStep } from "@/lib/api";

const TOOL_WORDS: Record<string, string> = {
  create_order: "Places the order",
  send_invoice: "Sends the invoice",
  get_deal: "Checks the deal",
};

const STATUS_WORDS: Record<string, string> = {
  WAITING_INVOICE: "Waiting for invoice", CHECKING: "Checking", HOLD: "On hold", CLEAR: "Clear", REFUSED: "Refused",
};

// Shown before the first run, so the visitor knows what to watch for.
const PREVIEW: AgentStep[] = [
  { actor: "Buyer's agent", text: "create_order", sal: "WAITING_INVOICE" },
  { actor: "Seller's billing system", text: "send_invoice with the wrong item code", sal: "HOLD" },
  { actor: "Seller's agent", text: "send_invoice with the correction", sal: "CLEAR" },
];

function plainCode(code: string): string {
  const words = code.toLowerCase().replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** "HOLD: ITEM_NOT_ORDERED, ITEM_NOT_INVOICED" from app/ai_agents.py, in words. */
function salAnswer(sal: string): { status: string; detail: string } {
  const [status, codes = ""] = sal.split(": ");
  return { status: STATUS_WORDS[status] ?? status, detail: codes.split(", ").filter(Boolean).map(plainCode).join(" · ") };
}

function actionWords(text: string): string {
  const tool = text.split(" ")[0];
  return TOOL_WORDS[tool] ? TOOL_WORDS[tool] + text.slice(tool.length) : text;
}

function StepRow({ step, faded }: { step: AgentStep; faded?: boolean }) {
  const answer = salAnswer(step.sal ?? "");
  return (
    <li className={`flex flex-col gap-0.5 py-2.5 text-[15px] sm:grid sm:grid-cols-[180px_1fr_auto] sm:gap-x-4 ${faded ? "muted" : ""}`}>
      <span className="font-semibold">{step.actor}</span>
      <span>{actionWords(step.text)}</span>
      <span className="sm:text-right">
        <span className="font-semibold">{answer.status}</span>
        {answer.detail && <span className="muted text-[13px] sm:block"><span className="sm:hidden"> · </span>{answer.detail}</span>}
      </span>
    </li>
  );
}

/** The buyer's last answer starts with PAY or WAIT (app/ai_agents.py asks for exactly that). */
function Decision({ step }: { step: AgentStep }) {
  const pays = step.text.trim().toUpperCase().startsWith("PAY");
  return (
    <p className="mt-2 rounded-xl bg-(--lp-card-2) px-4 py-3 text-[15px]">
      <span className="font-semibold">Buyer’s agent decides: {pays ? "pay" : "wait"}.</span>{" "}
      <span className="muted">{step.text.replace(/^\s*(PAY|WAIT)\W*/i, "")}</span>
    </p>
  );
}

/** Starts two AI agents in SAL's worker and shows each step with SAL's answer. */
export function AgentRunPanel({ run }: { run: AgentRun | null }) {
  const router = useRouter();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const working = run?.state === "QUEUED" || run?.state === "RUNNING";
  const steps = run?.state === "SUCCEEDED" ? run.result?.steps ?? [] : [];
  const calls = steps.filter((s) => s.sal !== null);
  const decision = [...steps].reverse().find((s) => s.sal === null && s.actor === "Buyer's agent");

  async function start() {
    setStarting(true);
    setError("");
    const result = await startAgentRun();
    setStarting(false);
    if (!result.ok) setError(result.message);
    router.refresh();
  }

  return (
    <div className="flex flex-col gap-3">
      {working && <AutoRefresh seconds={3} />}
      <div className="flex flex-wrap items-center justify-between gap-3">
        {working && run ? <Working label="The agents are working, about a minute" since={run.started_at} className="text-[15px]" />
          : <p className="muted text-[14px]">{calls.length ? `Last run: order ${run?.result?.deal_ref}` : "Not run yet"}</p>}
        <button type="button" onClick={start} disabled={starting || working} className="lp-btn">
          {working ? "Working…" : calls.length ? "Run again" : "Run the agents"}
        </button>
      </div>
      {error && <p role="alert" className="text-[15px] text-red-ink">{error}</p>}
      {run?.state === "FAILED" && !working && (
        <p role="alert" className="text-[15px] text-red-ink">The last run stopped early. Run it again.</p>
      )}
      <ol className="flex flex-col divide-y divide-(--lp-line) border-t border-(--lp-line)">
        {(calls.length ? calls : PREVIEW).map((step, i) => <StepRow key={i} step={step} faded={!calls.length} />)}
      </ol>
      {calls.length > 0 && decision && <Decision step={decision} />}
    </div>
  );
}
