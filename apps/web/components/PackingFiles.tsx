"use client";

import { useRef, useState } from "react";
import { uploadPacking } from "@/app/actions";

const MAX_IMAGE = 10 * 1024 * 1024;
const MAX_VIDEO = 50 * 1024 * 1024;

type Result = { name: string; ok: boolean; text: string };

/** Step 2: photos or a short video of the item going into the box. On a phone this opens the camera. */
export function PackingFiles({ packingId }: { packingId: string }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<Result[]>([]);
  const id = `packing-${packingId}`;

  async function send(files: FileList | null) {
    if (!files || files.length === 0) return;
    setBusy(true);
    const done: Result[] = [];
    for (const file of Array.from(files)) {  // one file per call keeps each request under the size limit
      const limit = file.type.startsWith("video/") ? MAX_VIDEO : MAX_IMAGE;
      if (file.size > limit) {
        done.push({ name: file.name, ok: false, text: `Larger than ${limit / 1024 / 1024} MB.` });
      } else {
        const form = new FormData();
        form.append("file", file);
        const r = await uploadPacking(packingId, form);
        done.push({ name: file.name, ok: r.ok, text: r.ok ? "Saved" : r.message });
      }
      setResults([...done]);
    }
    setBusy(false);
    if (input.current) input.current.value = "";
  }

  return (
    <div className="flex flex-col gap-2">
      <input ref={input} id={id} type="file" multiple className="sr-only" disabled={busy}
        accept="image/jpeg,image/png,image/gif,video/mp4,video/quicktime,video/webm" onChange={(e) => send(e.target.files)} />
      <label htmlFor={id} aria-disabled={busy}
        className={`lp-btn cursor-pointer text-center text-[15px] ${busy ? "pointer-events-none opacity-60" : ""}`}>
        {busy ? "Saving…" : "Add photos or video"}
      </label>
      {results.length > 0 && (
        <ul className="flex flex-col gap-1 text-sm" aria-live="polite">
          {results.map((r, i) => (
            <li key={i} className={r.ok ? "text-green-ink" : "text-red-ink"}>
              <span className="font-medium">{r.name}</span>: {r.text}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
