# ADR 0002: Deploy on Render free tier (Neon for Postgres)

**Status:** Accepted
**Date:** 2026-04-22
**Deciders:** Project owner (@birlaaishwarya11)

## Context

Per ADR 0001 the app is stateless over Postgres, so hosting is a
commodity choice: any container platform with an `$PORT` contract will
run it. The constraint is "free tier, no real spend." The DB is already
on Neon (serverless Postgres, 0.5 GB free, same decision tree in
ADR 0001).

## Decision

Deploy the web service on **Render free tier** (Dockerfile blueprint,
Ohio region to co-locate with Neon `us-east-1`) with auto-deploy from
the `main` branch. `render.yaml` at the repo root is the
source-of-truth for service config; the three secrets
(`DATABASE_URL`, `SECRET_KEY`, `FERNET_KEY`) are declared with
`sync: false` and set in the Render dashboard.

## Alternatives considered

### Railway (original plan)

Railway's free tier was removed in 2023; the entry-level plan is
$5/month minimum. Works well (same Dockerfile, easy DB plugin), but it
violates the "free" requirement.

### Fly.io

**Tried first; blocked.** Fly now requires a credit card on file
before provisioning any machine, even within the free allowance. A new
personal org has a machine quota of **zero** until the card is added;
this is anti-abuse, not billing. The CLI fails with:

```
Error: failed to determine region: failed to get placements:
requested machine count exceeds organization limit
```

A card would have unblocked Fly and given us a better runtime (no
sleep, faster cold-starts, always-on within free tier). Deferred to a
future revisit.

### TrueFoundry (with existing credits)

Supports our Docker image. Credits available. **Rejected for now**
because:
- Platform friction is higher (bring-your-own-cluster or managed setup
  vs. Render's "connect GitHub -> deploy").
- No `render.yaml`-equivalent we can commit; deploy config lives in
  their UI/CLI.
- Using credits for a hobby-traffic app is wasteful; keep them for
  workloads that actually need the capacity.

### Koyeb / PythonAnywhere / others

Not individually evaluated. The three above span the dominant free-tier
archetypes (always-on with card, sleep-based without card, credit-based
on k8s). Render won the "sleep-based without card" slot.

## Consequences

### Positive

- **Zero friction to start.** GitHub OAuth signup, no credit card, no
  CLI install required.
- **Blueprint-as-code.** `render.yaml` means the service config is in
  the repo, reviewable in PRs, and re-creatable if the Render project
  is deleted.
- **Auto-deploy on `main` push.** Commit -> build -> live in ~3-5 min.

### Negative

- **Sleeps after 15 minutes of inactivity.** First request after sleep
  eats a ~30 s cold start while the container wakes. Fine for a
  personal tool, painful for users we want to impress.
- **512 MB memory cap.** WeasyPrint rendering on a big, image-heavy
  PDF could OOM. Watch for 137 exit codes in logs; if we hit one,
  stream to a smaller rendering budget or move to a paid tier.
- **Single region (Ohio)** for the free tier. Co-located with Neon
  `us-east-1` for DB latency, but global users pay for the distance.

### Neutral

- **Dockerfile portability.** Same image runs on Fly, Railway,
  TrueFoundry, or a bare VM. Switching providers is a config change,
  not a code change, so this decision is reversible in an afternoon.

## Operational notes

- **Cold-start mitigation (optional):** set up an external
  health-check ping (UptimeRobot, cron-job.org) to hit `/health` every
  10 minutes. This keeps the service warm for the cost of ~250
  extra requests/day. Do not do this on any plan you actually pay for;
  it defeats the point of auto-sleep.
- **Known init race:** `gunicorn --workers N` caused two workers to
  race on `CREATE TABLE IF NOT EXISTS` (Postgres doesn't lock the
  catalog during the existence check). Fixed in `app/models.py` via
  `pg_advisory_xact_lock` around `init_db`.
- **Secrets hygiene:** `.env` is gitignored; production secrets only
  live in the Render dashboard and the local developer's machine.

## When to revisit

Trigger conditions that would motivate moving off Render:

1. **Real users complain about cold starts.** Fix: add a card, move
   to Render Starter ($7/mo) or Fly Hobby. Both kill sleep.
2. **Resume renders OOM on realistic input.** Fix: Render 2 GB tier
   ($25/mo) or migrate to Fly with a 1 GB VM.
3. **Global latency matters.** Fix: Fly's multi-region deploy with
   same-region Neon projection, or a Cloudflare Worker in front for
   static assets. Don't bother until the user base is non-trivial.
4. **TrueFoundry credits need to be spent** on something production-
   shaped. Migrate using the existing Dockerfile; re-use `render.yaml`
   as a reference for env-var wiring.

## References

- [render.yaml](../../render.yaml) -- current deployment config.
- Neon decision: [ADR 0001](0001-postgres-only-storage.md) section
  "Why Neon."
- Fly quota error documented in the deploy transcript for commit
  `8875c91`.
