# packages/shared

TypeScript types generated from the FastAPI OpenAPI schema (§11). Generated,
never hand-written: hand-maintained duplicates of an API contract drift
silently, and the first symptom is a runtime error in a paying customer's
browser.

```sh
make types                                  # regenerate types.ts
python packages/shared/generate.py --check  # fail if it is stale
```

`types.ts` is checked in so the web app builds without a Python toolchain,
and `tests/test_public_docs.py` re-runs the generator with `--check` so a
schema change that nobody regenerated fails the API suite rather than the
browser.

Two rules the generator applies that are not in the schema:

- **Request types get `?`, response types do not.** A field with a default
  is optional to send and always present in what comes back. Marking a
  response field optional makes every caller check for an absence the server
  never sends. Absence in a response is spelled `| null`.
- **Internal shapes are skipped** — FastAPI's generated multipart body names
  and the validation-error envelope are of no use outside the API.
