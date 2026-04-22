# ADR 0001: Postgres-only storage for per-user state

**Status:** Accepted
**Date:** 2026-04-21
**Deciders:** Project owner (@birlaaishwarya11)

## Context

The app was originally designed around a hybrid layout: relational data
(users, settings, resume version history, JD sessions, parsers) in PostgreSQL,
and per-user files (resume YAML, markdown databases, rules, the agent's
learning log, the cover-letter draft) on the local filesystem under
`data/{user_id}/`. PDFs were regenerated on each render and written to the
same directory before being served.

That layout works on a single long-lived server with a persistent disk. It
does **not** survive:

- Ephemeral compute (containers that redeploy with a fresh filesystem).
- Horizontal scale (two workers can't see each other's disk state).
- Free-tier platforms that don't ship a persistent volume by default.

We are deploying on a free tier. We need per-user state to survive deploys
and to be reachable from any worker.

### What actually lives on disk (audit findings)

A file-by-file audit (see commit history on this branch) found:

| File | Type | Size/user | Writes |
|---|---|---|---|
| `resume.yaml` | YAML | ~10 KB | Every edit, wholesale rewrite |
| `cover_letter_draft.yaml` | YAML | ~5 KB | Per edit, wholesale |
| `candidate_database.md` | Markdown | ~5 KB | User-edited |
| `resume_rules.md` | Markdown | ~2 KB | User-edited |
| `cover_letter_database.md` | Markdown | ~5 KB | User-edited |
| `cover_letter_rules.md` | Markdown | ~2 KB | User-edited |
| `resume_learnings.md` | Markdown, append | grows | Append per agent run |
| `preview.pdf`, `cover_letter.pdf` | Binary | ~200 KB | **Ephemeral** -- regenerated every render |
| `versions/*.yaml` | YAML | -- | **Legacy** -- already duplicated in `resume_versions` table |
| `onboarding_upload.pdf` | Binary | ~200 KB | Temporary during onboarding only |

**Total persistent state per user: ~30--40 KB of text.** No binary blobs
need to survive past a request. The legacy per-user version files duplicate
what `resume_versions` already stores.

## Decision

**Move every persistent per-user file into PostgreSQL.** Drop the
`data/{user_id}/` directory entirely. Do not introduce an object store.

- Introduce a `user_documents` table with one row per user and one `TEXT`
  column per document: `resume_yaml`, `cover_letter_draft_yaml`,
  `candidate_database`, `resume_rules`, `cover_letter_database`,
  `cover_letter_rules`, `resume_learnings`.
- Seed the row at signup with defaults read once from
  `data/defaults/*.md` (these ship with the app and are read-only).
- PDFs are generated in-memory with WeasyPrint (`write_pdf()` returning
  bytes) and streamed via `io.BytesIO`. Nothing touches the filesystem.
- The onboarding PDF, which must persist between `/api/upload_resume`
  and `/api/complete_onboarding`, is written to `tempfile.gettempdir()`
  with a per-user filename and deleted on completion.
- Legacy filesystem version history (`versions/*.yaml`) is removed. The
  `resume_versions` table is the sole version store. The three
  file-glob endpoints (`/api/history`, `/api/load/<file>`,
  `/api/delete_version/<file>`) are removed -- the frontend already
  consumes the DB-backed `/api/versions` endpoints.
- Feedback moves from `data/feedback.jsonl` into a `feedback` table.
- `resume_learnings` has a 64 KB cap per user; exceeding it trims the
  oldest `## Learning:` blocks, keeping the header.

## Alternatives considered

### Cloudflare R2 (or any S3-compatible object store)

Our first instinct. **Rejected for the current state** because:

1. **The data is text, not blobs.** Storing ~40 KB of YAML/markdown per
   user in an object store adds a second source of truth for no storage
   win. Neon's free tier (0.5 GB) holds ~12,500 users at this size --
   far beyond our near-term horizon.
2. **Two-system consistency tax.** "Save resume" becomes "write R2
   object + insert version row". These can desync. Keeping both writes
   in one DB transaction is free.
3. **No PDF persistence.** The original motivation for R2 was "1 PDF
   per user". The audit showed PDFs are ephemeral -- regenerated on
   every render -- so there's nothing to persist.
4. **Operational cost.** One more service to sign up for, one more key
   to rotate, one more dashboard to watch.
5. **Reachability.** R2 is a reversible decision. If persistent PDFs
   become a feature (e.g., "download history of my submitted
   resumes"), we add R2 *only for that use case*, behind a thin
   adapter in `app/services/`. The text stays in Postgres either way.

### Supabase Storage / Backblaze B2

Same reasoning as R2 -- no text-storage win, extra service, no binary
need. Plus Supabase Storage's value proposition is its auth
integration, which we're not adopting.

### Hybrid (R2 adapter stubbed now, unused)

We considered building `services/storage.py` as a Postgres-backed
adapter with an R2 implementation ready to swap. **Rejected** because
the abstraction is premature: we don't know the shape of the future
blob need (versioned PDFs? attachments? user uploads?), and building
the wrong abstraction now is worse than adding it later against a real
requirement.

### Keep filesystem + use Fly/Railway persistent volumes

Works, but pins us to a specific host (volumes don't migrate between
providers) and breaks horizontal scale. Also requires provisioning a
volume even at one-user scale.

## Consequences

### Positive

- **One storage system.** Every write is a single DB transaction.
- **Stateless compute.** Workers can scale to N replicas with no
  shared disk.
- **Portable.** Fly, Railway, Render, a bare VM -- they all work.
  Moving providers is a `DATABASE_URL` change.
- **Smaller deploy surface.** No `DATA_DIR`, no volume mount, no PDF
  disk bloat.
- **Free-tier fit.** Neon's 0.5 GB holds ~12,500 users' worth of
  documents; Neon auto-suspends when idle so we pay nothing at
  zero traffic.

### Negative

- **Row-size growth on `resume_learnings`.** Mitigated by the 64 KB
  cap + trim-oldest on append.
- **PDF rendering hits CPU on every download.** WeasyPrint is ~200-500 ms
  per render. Acceptable at current traffic; if it becomes hot, we
  add a short-lived in-memory cache keyed on `(user_id, yaml_hash)`.
- **DB is a single point of failure.** It already was -- users,
  sessions, parsers, versions all lived there. This just moves the
  last 40 KB of per-user state onto the same failure domain.

### Neutral

- **`data/defaults/`** still ships on disk as read-only application
  assets. We read them once at signup to seed new users. They are
  never written to and are safe to ship inside the container.
- **`.fernet_key`** was never in `data/`; unchanged. `FERNET_KEY` env
  var in prod.

## When to revisit

Trigger conditions that would motivate adding an object store:

1. **Persistent PDF artifacts** -- e.g., a "submissions history"
   feature where a rendered PDF must survive the request. Add R2 for
   these objects only.
2. **User-uploaded binary assets** larger than text (PDF portfolios,
   images, video intros).
3. **`resume_learnings` or candidate databases growing past a MB per
   user** (signals a model that doesn't fit relational storage).
4. **Multi-region latency complaints** -- object storage has better
   edge-delivery characteristics than Postgres.

In every case, the migration path is: add `app/services/storage.py`
with an R2 backend, migrate only the relevant fields, keep text in
Postgres.

## References

- Audit: see the change log on commit introducing this ADR.
- Related files: `app/models.py` (schema), `app/services/documents.py`
  (facade), `app/agents/jd_resume.py` (in-memory PDF render).
