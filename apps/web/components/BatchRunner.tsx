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
import { Button, Card, Meter, Muted, Notice, Pill, type Tone } from "./ui";

/**
 * §7 batch flow: multi-drop up to 500 → presigned uploads → server-persisted
 * progress grid → per-file retry → zip download.
 *
 * "Closing the tab must not lose work." The batch id lives in localStorage
 * and the grid is rebuilt from the server on the next visit — the browser is
 * a *view* of the run, never its record. That is also why the resumed state
 * has its own copy: coming back to "38 of 42 finished while you were away"
 * is the moment the feature justifies itself.
 */

const MAX_FILES = 500;
const STORAGE_KEY = "v4u.batch.current";
const UPLOAD_CONCURRENCY = 6;

const STATE_TONE: Record<string, Tone> = {
  complete: "green",
  failed: "magenta",
  processing: "cyan",
  queued: "neutral",
};

const STATE_LABEL: Record<string, string> = {
  complete: "done",
  failed: "failed",
  processing: "tracing",
  queued: "queued",
};

export default function BatchRunner() {
  const [batch, setBatch] = useState<Batch | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [resumed, setResumed] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [uploaded, setUploaded] = useState({ done: 0, total: 0 });
  const [dragOver, setDragOver] = useState(false);
  const [token] = useState<string | null>(null); // wired to the auth provider in Phase 4
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (!saved || !token) return;
    getBatch(saved, token)
      .then((found) => {
        setBatch(found);
        setResumed(true);
      })
      .catch(() => window.localStorage.removeItem(STORAGE_KEY));
  }, [token]);

  useEffect(() => {
    if (!batch || !token || batch.status === "complete") return;
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
      setResumed(false);
      setMessage(null);
      setUploaded({ done: 0, total: files.length });

      try {
        const maxBytes = Math.max(...files.map((f) => f.size));
        const created = await createBatch(files.length, {}, maxBytes, token);
        window.localStorage.setItem(STORAGE_KEY, created.batch_id);

        // Straight to storage, never through this server: 500 × 25 MB is
        // 12.5 GB and would not survive a single request (§4.3).
        const queue = created.slots.map((slot, index) => ({ slot, file: files[index] }));
        const pending = [...queue];
        await Promise.all(
          Array.from({ length: Math.min(UPLOAD_CONCURRENCY, pending.length) }, async () => {
            for (;;) {
              const next = pending.shift();
              if (!next) return;
              await putToStorage(next.slot.put_url, next.file, next.slot.headers);
              setUploaded((prev) => ({ ...prev, done: prev.done + 1 }));
            }
          }),
        );

        const started = await startBatch(
          created.batch_id,
          created.slots.map((slot) => slot.upload_id),
          token,
        );
        setBatch(started);
        setNames(
          Object.fromEntries(
            started.files.map((file, index) => [file.job_id, files[index]?.name ?? file.job_id]),
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

  const retryAll = useCallback(async () => {
    if (!batch) return;
    for (const file of batch.files.filter((f) => f.status === "failed")) {
      await retry(file.job_id);
    }
  }, [batch, retry]);

  if (!batch) {
    return (
      <>
        {message && (
          <Notice tone="magenta" title="Heads up">
            {message}
          </Notice>
        )}
        <div
          onDragOver={(event) => {
            event.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragOver(false);
            void run([...event.dataTransfer.files]);
          }}
          style={{
            border: `1px dashed ${dragOver ? "var(--cyan)" : "var(--ink-200)"}`,
            background: dragOver ? "var(--cyan-soft)" : "var(--ink-0)",
            borderRadius: "var(--radius-lg)",
            padding: "var(--space-8) var(--space-5)",
            textAlign: "center",
            display: "grid",
            gap: "var(--space-3)",
            justifyItems: "center",
          }}
        >
          <div style={{ fontWeight: 500, color: "var(--ink-900)", fontSize: "var(--text-lg)" }}>
            Drop up to {MAX_FILES} files here
          </div>
          <p style={{ color: "var(--ink-500)", margin: 0, maxWidth: "52ch" }}>
            PNG, JPEG or WEBP. You can close this tab while they run — progress comes back when
            you return.
          </p>
          <label>
            <Button variant="primary" size="lg">
              Choose files
            </Button>
            <input
              type="file"
              multiple
              accept="image/*"
              style={{ display: "none" }}
              onChange={(event) => void run([...(event.target.files ?? [])])}
            />
          </label>
          {busy && (
            <Muted size="xs">
              Uploading {uploaded.done} of {uploaded.total}…
            </Muted>
          )}
        </div>
      </>
    );
  }

  const failed = batch.files.filter((f) => f.status === "failed").length;
  const progress = batch.total ? batch.completed / batch.total : 0;

  return (
    <div style={{ display: "grid", gap: "var(--space-4)" }}>
      {message && (
        <Notice tone="magenta" title="Heads up">
          {message}
        </Notice>
      )}

      {resumed && (
        <Notice
          tone="cyan"
          title="Picked up where you left off"
          actions={
            failed > 0 && (
              <Button size="sm" variant="primary" onClick={() => void retryAll()}>
                Retry {failed} {failed === 1 ? "file" : "files"}
              </Button>
            )
          }
        >
          {batch.completed} of {batch.total} finished while you were away
          {failed > 0 ? `, ${failed} need a retry.` : "."}
        </Notice>
      )}

      <Card>
        <div style={{ display: "flex", gap: "var(--space-4)", alignItems: "center", flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 220 }}>
            <Meter value={progress} tone={failed ? "amber" : "cyan"} label="Batch progress" />
            <div style={{ marginTop: 6, fontSize: "var(--text-sm)", color: "var(--ink-500)" }}>
              {batch.completed} of {batch.total} done
              {failed > 0 && ` · ${failed} failed`}
              {batch.status !== "complete" && " · still running"}
            </div>
          </div>
          {batch.zip_url && (
            <a href={batch.zip_url} download style={{ textDecoration: "none" }}>
              <Button variant="primary">Download all as zip</Button>
            </a>
          )}
        </div>
      </Card>

      <ul
        style={{
          listStyle: "none",
          margin: 0,
          padding: 0,
          display: "grid",
          gap: "var(--space-3)",
          gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
        }}
      >
        {batch.files.map((file) => {
          const tone = STATE_TONE[file.status] ?? "neutral";
          return (
            <li
              key={file.job_id}
              style={{
                border: `1px solid ${file.status === "failed" ? "var(--magenta-border)" : "var(--ink-100)"}`,
                borderRadius: "var(--radius-md)",
                background: "var(--ink-0)",
                padding: "var(--space-3)",
                display: "grid",
                gap: 6,
              }}
            >
              <div
                style={{
                  fontSize: "var(--text-sm)",
                  color: "var(--ink-900)",
                  fontWeight: 500,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
                title={names[file.job_id] ?? file.job_id}
              >
                {names[file.job_id] ?? file.job_id.slice(4, 16)}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Pill tone={tone}>{STATE_LABEL[file.status] ?? file.status}</Pill>
                {file.status === "failed" && (
                  <Button size="sm" onClick={() => void retry(file.job_id)}>
                    Retry
                  </Button>
                )}
              </div>
              {file.error_code && <Muted size="xs">{file.error_code.replace(/_/g, " ")}</Muted>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
