"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  type Batch,
  createBatch,
  getBatch,
  putToStorage,
  retryBatchFile,
  startBatch,
} from "@/lib/api";

/**
 * §7 batch flow: multi-drop up to 500 → presigned uploads → server-persisted
 * progress grid → per-file retry → zip download.
 *
 * "Closing the tab must not lose work": the batch id goes into localStorage
 * and the grid is rebuilt from the server on the next visit. The browser is
 * a view of the run, never its record.
 */

const MAX_FILES = 500;
const STORAGE_KEY = "vectorize.batch.current";

export default function BatchRunner() {
  const [batch, setBatch] = useState<Batch | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [uploaded, setUploaded] = useState({ done: 0, total: 0 });
  const [token] = useState<string | null>(null); // wired to the auth provider in Phase 4
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Resume whatever run was in flight when the tab closed.
  useEffect(() => {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (!saved || !token) return;
    getBatch(saved, token)
      .then(setBatch)
      .catch(() => window.localStorage.removeItem(STORAGE_KEY));
  }, [token]);

  useEffect(() => {
    if (!batch || !token) return;
    if (batch.status === "complete") return;
    pollRef.current = setTimeout(() => {
      getBatch(batch.id, token).then(setBatch).catch(() => undefined);
    }, 2000);
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [batch, token]);

  const run = useCallback(
    async (files: File[]) => {
      if (!token) {
        setMessage("Sign in to run a batch. Batches are stored against your account.");
        return;
      }
      if (files.length > MAX_FILES) {
        setMessage(`That's ${files.length} files. The maximum is ${MAX_FILES}.`);
        return;
      }
      setBusy(true);
      setMessage(null);
      setUploaded({ done: 0, total: files.length });

      try {
        const maxBytes = Math.max(...files.map((f) => f.size));
        const created = await createBatch(files.length, {}, maxBytes, token);
        window.localStorage.setItem(STORAGE_KEY, created.batch_id);

        // Uploads go straight to storage, never through this server: 500 ×
        // 25 MB is 12.5 GB and would not survive a single request (§4.3).
        // Six at a time keeps the browser's connection pool useful.
        const queue = [...created.slots.map((slot, index) => ({ slot, file: files[index] }))];
        const workers = Array.from({ length: Math.min(6, queue.length) }, async () => {
          for (;;) {
            const next = queue.shift();
            if (!next) return;
            await putToStorage(next.slot.put_url, next.file, next.slot.headers);
            setUploaded((prev) => ({ ...prev, done: prev.done + 1 }));
          }
        });
        await Promise.all(workers);

        setBatch(
          await startBatch(
            created.batch_id,
            created.slots.map((slot) => slot.upload_id),
            token,
          ),
        );
      } catch (error) {
        setMessage(
          error instanceof ApiError ? error.problem.detail : "The batch could not be started.",
        );
      } finally {
        setBusy(false);
      }
    },
    [token],
  );

  const retry = useCallback(
    async (jobId: string) => {
      if (!batch || !token) return;
      try {
        setBatch(await retryBatchFile(batch.id, jobId, token));
      } catch (error) {
        setMessage(error instanceof ApiError ? error.problem.detail : "Retry failed.");
      }
    },
    [batch, token],
  );

  return (
    <div className="space-y-6">
      <div
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          void run([...event.dataTransfer.files]);
        }}
        className="rounded-lg border-2 border-dashed border-slate-300 p-10 text-center dark:border-slate-700"
      >
        <p className="text-lg font-medium">Drop up to {MAX_FILES} images</p>
        <label className="mt-3 inline-block cursor-pointer rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">
          Choose files
          <input
            type="file"
            multiple
            accept="image/*"
            className="sr-only"
            onChange={(event) => void run([...(event.target.files ?? [])])}
          />
        </label>
      </div>

      {busy && (
        <p role="status" aria-live="polite" className="text-sm">
          Uploading {uploaded.done} of {uploaded.total}…
        </p>
      )}

      {message && (
        <p role="alert" className="rounded bg-amber-50 p-3 text-sm dark:bg-amber-950/40">
          {message}
        </p>
      )}

      {batch && (
        <section className="space-y-4" aria-labelledby="progress-heading">
          <div className="flex flex-wrap items-baseline gap-3">
            <h2 id="progress-heading" className="text-lg font-semibold">
              Progress
            </h2>
            <p className="text-sm text-slate-600 dark:text-slate-300">
              {batch.completed} of {batch.total} done
              {batch.failed > 0 && `, ${batch.failed} failed`}
            </p>
            {batch.zip_url && (
              <a
                href={batch.zip_url}
                className="ml-auto rounded bg-slate-900 px-3 py-2 text-sm font-medium text-white dark:bg-slate-100 dark:text-slate-900"
                download
              >
                Download all as .zip
              </a>
            )}
          </div>

          <div
            className="h-2 w-full overflow-hidden rounded bg-slate-200 dark:bg-slate-700"
            role="progressbar"
            aria-valuenow={batch.completed}
            aria-valuemin={0}
            aria-valuemax={batch.total}
          >
            <div
              className="h-full bg-blue-600 transition-[width]"
              style={{ width: `${batch.total ? (batch.completed / batch.total) * 100 : 0}%` }}
            />
          </div>

          <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {batch.files.map((file) => (
              <li
                key={file.job_id}
                className="flex items-center justify-between gap-2 rounded border border-slate-200 px-3 py-2 text-sm dark:border-slate-700"
              >
                <span className="truncate font-mono text-xs">{file.job_id.slice(4, 14)}</span>
                <span
                  className={
                    file.status === "complete"
                      ? "text-green-700 dark:text-green-400"
                      : file.status === "failed"
                        ? "text-red-700 dark:text-red-400"
                        : "text-slate-500"
                  }
                >
                  {file.status}
                </span>
                {file.status === "failed" && (
                  <button
                    type="button"
                    onClick={() => void retry(file.job_id)}
                    className="rounded border border-slate-300 px-2 py-0.5 text-xs dark:border-slate-600"
                  >
                    Retry
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
