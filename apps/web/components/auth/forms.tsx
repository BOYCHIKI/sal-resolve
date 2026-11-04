"use client";

import { useActionState, useId, useState, useTransition } from "react";
import { useFormStatus } from "react-dom";
import {
  changePassword, disableTwoStep, enableTwoStep, signIn, signOutOthers, signUp, startTwoStep, verifyCode, type FormState,
} from "@/app/auth-actions";

const INPUT = "min-h-11 w-full rounded-xl border border-(--lp-line-strong) bg-white px-3 py-2 text-[15px]";

function Input({ label, hint, ...props }: React.InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string }) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-[14px] font-semibold">{label}</label>
      <input id={id} className={INPUT} {...props} />
      {hint && <span className="muted text-[13px]">{hint}</span>}
    </div>
  );
}

function PasswordInput(props: React.InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string }) {
  const [shown, setShown] = useState(false);
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between">
        <label htmlFor={id} className="text-[14px] font-semibold">{props.label}</label>
        <button type="button" onClick={() => setShown(!shown)} className="muted text-[13px] hover:underline"
          aria-controls={id} aria-pressed={shown}>{shown ? "Hide" : "Show"}</button>
      </div>
      <input id={id} type={shown ? "text" : "password"} className={INPUT} maxLength={128} {...props} />
      {props.hint && <span className="muted text-[13px]">{props.hint}</span>}
    </div>
  );
}

function Submit({ children, wide = true }: { children: React.ReactNode; wide?: boolean }) {
  const { pending } = useFormStatus();
  return (
    <button type="submit" disabled={pending} className={`lp-btn text-[15px] ${wide ? "w-full" : ""}`}>
      {pending ? "Please wait…" : children}
    </button>
  );
}

function Message({ state }: { state: FormState }) {
  if (state?.error) return <p role="alert" className="rounded-xl bg-red-bg px-4 py-3 text-[14px] text-red-ink">{state.error}</p>;
  if (state?.done) return <p role="status" className="rounded-xl bg-green-bg px-4 py-3 text-[14px] text-green-ink">{state.done}</p>;
  return null;
}

// ---------------------------------------------------------------- signing in and up
export function SignInForm({ next }: { next: string }) {
  const [state, action] = useActionState(signIn, undefined);
  return (
    <form action={action} className="flex flex-col gap-4">
      <input type="hidden" name="next" value={next} />
      <Input key={state?.email} label="Email" name="email" type="email" autoComplete="email" required maxLength={254}
        defaultValue={state?.email} autoFocus={!state?.email} />
      <PasswordInput label="Password" name="password" autoComplete="current-password" required autoFocus={!!state?.email} />
      <Message state={state} />
      <Submit>Sign in</Submit>
    </form>
  );
}

export function VerifyForm({ next }: { next: string }) {
  const [state, action] = useActionState(verifyCode, undefined);
  const [recovery, setRecovery] = useState(false);
  return (
    <form action={action} className="flex flex-col gap-4">
      <input type="hidden" name="next" value={next} />
      {recovery ? (
        <Input key="recovery" label="Recovery code" name="code" autoComplete="off" required maxLength={20}
          placeholder="abcde-fghjk" autoFocus hint="Each recovery code works once." />
      ) : (
        <Input key="totp" label="6-digit code" name="code" inputMode="numeric" autoComplete="one-time-code" required
          maxLength={6} pattern="[0-9]{6}" placeholder="123456" autoFocus className={`${INPUT} text-center text-[22px] tracking-[0.4em]`} />
      )}
      <Message state={state} />
      <Submit>Verify</Submit>
      <button type="button" onClick={() => setRecovery(!recovery)} className="muted text-[14px] hover:underline">
        {recovery ? "Use the authenticator app instead" : "Lost your phone? Use a recovery code"}
      </button>
    </form>
  );
}

export function SignUpForm() {
  const [state, action] = useActionState(signUp, undefined);
  return (
    <form action={action} className="flex flex-col gap-4">
      <Input label="Business name" name="business" autoComplete="organization" required maxLength={120} autoFocus />
      <Input label="Work email" name="email" type="email" autoComplete="email" required maxLength={254} />
      <PasswordInput label="Password" name="password" autoComplete="new-password" required minLength={12}
        hint="At least 12 characters. A short sentence is easy to remember and hard to guess." />
      <PasswordInput label="Type the password again" name="confirm" autoComplete="new-password" required minLength={12} />
      <Message state={state} />
      <Submit>Create account</Submit>
    </form>
  );
}

// ---------------------------------------------------------------- the account page
export function TwoStepSetup() {
  const [setup, setSetup] = useState<FormState>(undefined);
  const [starting, start] = useTransition();
  const [state, action] = useActionState(enableTwoStep, undefined);

  if (state?.codes) {
    return (
      <div className="flex flex-col gap-3">
        <p role="status" className="rounded-xl bg-green-bg px-4 py-3 text-[14px] text-green-ink">
          Two-step sign-in is on. Other sessions were signed out.
        </p>
        <p className="text-[15px] font-semibold">Save these recovery codes now. They are shown only once.</p>
        <p className="muted text-[14px]">If you lose your phone, each code lets you sign in one time.</p>
        <ol className="grid grid-cols-2 gap-2 rounded-xl bg-(--lp-card-2) p-4 font-mono text-[15px]">
          {state.codes.map((c) => <li key={c}>{c}</li>)}
        </ol>
        <button type="button" onClick={() => navigator.clipboard?.writeText(state.codes!.join("\n"))}
          className="lp-btn-ghost self-start text-[14px]">Copy codes</button>
      </div>
    );
  }
  if (!setup?.qr) {
    return (
      <div className="flex flex-col gap-3">
        <button type="button" disabled={starting} className="lp-btn self-start text-[15px]"
          onClick={() => start(async () => setSetup(await startTwoStep()))}>
          {starting ? "Please wait…" : "Turn on two-step sign-in"}
        </button>
        <Message state={setup} />
      </div>
    );
  }
  return (
    <form action={action} className="flex flex-col gap-4">
      <ol className="flex list-decimal flex-col gap-1 pl-5 text-[15px]">
        <li>Open an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password…).</li>
        <li>Scan this code, or type the key below.</li>
        <li>Enter the 6-digit code the app shows.</li>
      </ol>
      {/* eslint-disable-next-line @next/next/no-img-element -- a data: URI made by the API, no remote image */}
      <img src={setup.qr} alt="QR code for your authenticator app" width={180} height={180} className="rounded-xl bg-white p-2" />
      <p className="muted text-[13px]">Key: <span className="font-mono text-(--lp-ink) [overflow-wrap:anywhere]">{setup.secret?.match(/.{1,4}/g)?.join(" ")}</span></p>
      <Input label="6-digit code" name="code" inputMode="numeric" autoComplete="one-time-code" required maxLength={6} pattern="[0-9]{6}" />
      <Message state={state} />
      <Submit wide={false}>Confirm and turn on</Submit>
    </form>
  );
}

export function TwoStepOff() {
  const [state, action] = useActionState(disableTwoStep, undefined);
  const [open, setOpen] = useState(false);
  if (state?.done) return <Message state={state} />;
  if (!open) {
    return <button type="button" onClick={() => setOpen(true)} className="text-[14px] text-red-ink hover:underline">Turn off two-step sign-in</button>;
  }
  return (
    <form action={action} className="flex flex-col gap-4">
      <p className="muted text-[14px]">To turn it off, confirm with your password and a current code.</p>
      <PasswordInput label="Password" name="password" autoComplete="current-password" required />
      <Input label="6-digit code" name="code" inputMode="numeric" autoComplete="one-time-code" required maxLength={6} pattern="[0-9]{6}" />
      <Message state={state} />
      <Submit wide={false}>Turn off</Submit>
    </form>
  );
}

export function ChangePasswordForm() {
  const [state, action] = useActionState(changePassword, undefined);
  return (
    <form action={action} className="flex flex-col gap-4">
      <PasswordInput label="Current password" name="current" autoComplete="current-password" required />
      <PasswordInput label="New password" name="new" autoComplete="new-password" required minLength={12} hint="At least 12 characters." />
      <PasswordInput label="Type the new password again" name="confirm" autoComplete="new-password" required minLength={12} />
      <Message state={state} />
      <Submit wide={false}>Change password</Submit>
    </form>
  );
}

export function SignOutOthersButton() {
  const [state, setState] = useState<FormState>(undefined);
  const [busy, run] = useTransition();
  return (
    <div className="flex flex-col gap-2">
      <button type="button" disabled={busy} onClick={() => run(async () => setState(await signOutOthers()))}
        className="lp-btn-ghost self-start text-[14px]">{busy ? "Please wait…" : "Sign out of all other sessions"}</button>
      <Message state={state} />
    </div>
  );
}
