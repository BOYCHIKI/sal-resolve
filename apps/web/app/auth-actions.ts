"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { auth } from "@/lib/api";
import { cookieOptions, PENDING_COOKIE, PENDING_SECONDS, safeNext, SESSION_COOKIE, SESSION_SECONDS } from "@/lib/session";

export type FormState = { error?: string; done?: string; codes?: string[]; qr?: string; secret?: string; email?: string } | undefined;

const UNREACHABLE = "SAL can’t reach its server right now. Try again in a moment.";

function field(form: FormData, name: string, max = 254): string {
  return String(form.get(name) ?? "").slice(0, max);
}

async function startSession(token: string, next: string): Promise<never> {
  const jar = await cookies();
  jar.delete(PENDING_COOKIE);
  jar.set(SESSION_COOKIE, token, cookieOptions(SESSION_SECONDS));
  redirect(safeNext(next));
}

export async function signIn(_: FormState, form: FormData): Promise<FormState> {
  const next = field(form, "next", 500);
  const email = field(form, "email");   // given back so the form keeps it; the password is never sent back
  let reply;
  try {
    reply = await auth.signIn(email, field(form, "password", 128));
  } catch {
    return { error: UNREACHABLE, email };
  }
  if (!reply.ok) return { error: reply.message, email };
  if (reply.stage === "MFA_PENDING") {
    (await cookies()).set(PENDING_COOKIE, reply.token, cookieOptions(PENDING_SECONDS));
    redirect(`/login/verify?next=${encodeURIComponent(safeNext(next))}`);
  }
  return startSession(reply.token, next);
}

export async function verifyCode(_: FormState, form: FormData): Promise<FormState> {
  const pending = (await cookies()).get(PENDING_COOKIE)?.value;
  if (!pending) redirect("/login?expired=1");
  let reply;
  try {
    reply = await auth.finishSignIn(pending, field(form, "code", 20));
  } catch {
    return { error: UNREACHABLE };
  }
  if (!reply.ok) {
    if (reply.code === "MFA_EXPIRED") redirect("/login?expired=1");
    return { error: reply.message };
  }
  return startSession(reply.token, field(form, "next", 500));
}

export async function signUp(_: FormState, form: FormData): Promise<FormState> {
  const password = field(form, "password", 128);
  if (password !== field(form, "confirm", 128)) return { error: "The two passwords are different." };
  let reply;
  try {
    reply = await auth.signUp(field(form, "business", 120), field(form, "email"), password);
  } catch {
    return { error: UNREACHABLE };
  }
  if (!reply.ok) return { error: reply.message };
  return startSession(reply.token, "/account?welcome=1");
}

export async function signOut(): Promise<void> {
  try {
    await auth.signOut();
  } finally {
    (await cookies()).delete(SESSION_COOKIE);
  }
  redirect("/login?signed_out=1");
}

export async function signOutOthers(): Promise<FormState> {
  const reply = await auth.signOutOthers().catch(() => null);
  if (!reply?.ok) return { error: reply?.message ?? UNREACHABLE };
  return { done: reply.signed_out ? `Signed out of ${reply.signed_out} other session${reply.signed_out === 1 ? "" : "s"}.` : "No other sessions were open." };
}

export async function changePassword(_: FormState, form: FormData): Promise<FormState> {
  const next = field(form, "new", 128);
  if (next !== field(form, "confirm", 128)) return { error: "The two new passwords are different." };
  const reply = await auth.changePassword(field(form, "current", 128), next).catch(() => null);
  if (!reply?.ok) return { error: reply?.message ?? UNREACHABLE };
  return { done: "Password changed. Every other session was signed out." };
}

export async function startTwoStep(): Promise<FormState> {
  const reply = await auth.startTwoStep().catch(() => null);
  if (!reply?.ok) return { error: reply?.message ?? UNREACHABLE };
  return { qr: reply.qr_svg, secret: reply.secret };
}

export async function enableTwoStep(_: FormState, form: FormData): Promise<FormState> {
  const reply = await auth.enableTwoStep(field(form, "code", 20)).catch(() => null);
  if (!reply?.ok) return { error: reply?.message ?? UNREACHABLE };
  return { codes: reply.recovery_codes };
}

export async function disableTwoStep(_: FormState, form: FormData): Promise<FormState> {
  const reply = await auth.disableTwoStep(field(form, "password", 128), field(form, "code", 20)).catch(() => null);
  if (!reply?.ok) return { error: reply?.message ?? UNREACHABLE };
  return { done: "Two-step sign-in is off." };
}
