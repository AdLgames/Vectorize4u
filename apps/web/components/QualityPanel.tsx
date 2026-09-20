import type { Job } from "@/lib/api";
import { describeWarning } from "@/lib/warnings";

/**
 * The exposed quality score (§6).
 *
 * "Exposing the quality score is a differentiator and a support-cost
 * reducer: it turns 'this looks bad' into a number both sides can see."
 * The `score_version` is always shown with it, because scores from different
 * versions are not comparable.
 */

const CLASS_LABEL: Record<string, string> = {
  LOGO_FLAT: "Flat logo",
  LOGO_GRADIENT: "Gradient logo",
  LINE_ART: "Line art",
  SKETCH: "Sketch",
  ILLUSTRATION: "Illustration",
  PHOTO: "Photograph",
  SCREENSHOT: "Screenshot",
};

export default function QualityPanel({ job }: { job: Job }) {
  if (!job.quality) return null;
  const q = job.quality;

  return (
    <section aria-labelledby="quality-heading" className="space-y-4">
      <h2 id="quality-heading" className="text-lg font-semibold">
        Quality
      </h2>

      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Match" value={`${Math.round(q.fidelity * 100)}%`} hint="How close to your original" />
        <Stat label="Points" value={q.nodes.toLocaleString()} hint="Fewer cuts more cleanly" />
        <Stat label="Paths" value={q.paths.toLocaleString()} hint="Separate shapes" />
        <Stat
          label="Detected"
          value={job.classification ? (CLASS_LABEL[job.classification] ?? job.classification) : "—"}
          hint={
            job.classification_confidence !== null
              ? `${Math.round(job.classification_confidence * 100)}% confident`
              : ""
          }
        />
      </dl>

      <p className="text-xs text-slate-500 dark:text-slate-400">
        Score {q.total.toFixed(3)} · version {q.score_version}. Scores are only
        comparable within the same version.
      </p>

      {job.physical_size && (
        <p className="text-sm">
          Opens at{" "}
          <strong>
            {job.physical_size.width_mm.toFixed(1)} × {job.physical_size.height_mm.toFixed(1)} mm
          </strong>{" "}
          {job.physical_size.source === "user" ? (
            <span className="text-green-700 dark:text-green-400">(the size you asked for)</span>
          ) : job.physical_size.source === "metadata" ? (
            <span className="text-slate-500">(from the file’s own resolution)</span>
          ) : (
            <span className="text-amber-700 dark:text-amber-400">
              (assumed — set a width below before cutting)
            </span>
          )}
        </p>
      )}

      {job.warnings.length > 0 && (
        <ul className="space-y-2">
          {job.warnings.map((code) => {
            const warning = describeWarning(code);
            return (
              <li
                key={code}
                className={`rounded border-l-4 p-3 text-sm ${
                  warning.tone === "warn"
                    ? "border-amber-500 bg-amber-50 dark:bg-amber-950/40"
                    : "border-slate-300 bg-slate-50 dark:border-slate-600 dark:bg-slate-900"
                }`}
              >
                <strong className="block">{warning.title}</strong>
                {warning.detail && <span className="text-slate-600 dark:text-slate-300">{warning.detail}</span>}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded border border-slate-200 p-3 dark:border-slate-700">
      <dt className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="text-xl font-semibold tabular-nums">{value}</dd>
      {hint && <p className="text-xs text-slate-500 dark:text-slate-400">{hint}</p>}
    </div>
  );
}
