# ADR 0003: Reduce editor/cover-letter tab-switch latency

**Status:** Accepted
**Date:** 2026-04-22
**Deciders:** Project owner (@birlaaishwarya11)

## Context

Users reported noticeable latency when navigating between the Editor and
Cover Letter tabs -- roughly 1-1.5s of perceived lag before the editor
finishes painting and the preview shows up. On Render free tier + Neon
(`us-east-1`, serverless), even a warm instance hits a 50-150ms RTT per
Postgres query, so any DB fanout on the hot path is painful.

An audit of the editor's render path found the cost in three places:

1. **Settings fanout.** `editor.index()` called
   `get_current_user_header()`, `get_current_section_names()`, and
   `get_current_custom_sections()` separately. Each helper opens its own
   DB connection and runs the same `SELECT * FROM user_settings`. A
   fourth direct `get_user_settings()` call built the style dict.
   That's four identical round trips for one logical read.

2. **Jinja environment rebuilt per render.**
   `_render_resume_html()` and `_render_cover_letter_html()` constructed
   a fresh `Environment(loader=FileSystemLoader(TEMPLATE_DIR))` and
   reparsed the ~350-line `resume.html` on every call. Flask's
   app-level `jinja_env` was already caching templates -- we just
   weren't using it.

3. **Initial preview fetch.** `editor.js` fired a `fetch('/api/preview')`
   200ms after page load to populate the iframe, adding a full network
   round trip (and another template render) before the user saw
   anything, even though the editor route already had the YAML in hand.

Tab switches themselves are full page reloads (`<a href>` in `base.html`).
An SPA-style swap would shave another 200-500ms but is a much bigger
change; we decided to pick the cheap wins first.

## Options considered

| # | Change | Est. savings | Complexity | Picked? |
|---|---|---|---|---|
| 1 | Use Flask's app-level Jinja env; register `md_bold` as a global filter | 50-200ms per preview | trivial | **yes** |
| 2 | Cache `user_settings` once per request on `flask.g`; route helpers read from cache | 150-450ms per editor page load (3x round trips collapsed) | low | **yes** |
| 3 | Server-render the initial preview HTML into `<iframe srcdoc>`; drop the 200ms auto-fetch | 1 full round trip on first paint (~200-800ms depending on cold/warm) | low | **yes** |
| 4 | Move `inject_user` context processor to a `before_request` hook that caches on `g`, with API-route bypass | ~1 DB query per render | low | deferred -- user is only read in a few templates; small win, more touch points |
| 5 | Connection pooling (`psycopg2.pool.ThreadedConnectionPool`) | 20-80ms per query, compounding | medium | deferred -- bigger refactor, impacts `get_db()`/`init_db()` contract |
| 6 | SPA-style tab nav (fetch partial HTML, keep Ace alive) | 200-500ms perceived latency | higher | deferred -- structural change, revisit if #1-3 don't feel fast enough |

Options 1-3 together are ~30 lines of code and no architectural change.
Options 4-6 are listed for a future ADR if latency still feels bad after
this lands.

## Decision

Implement the **trio** (options 1, 2, 3 above).

### 1. Share the Flask Jinja env across blueprints

- `app/__init__.py`: register `md_bold` on `app.jinja_env.filters` once
  in `create_app()`.
- `app/blueprints/editor.py` and `app/blueprints/cover_letter.py`:
  replace hand-rolled `Environment(loader=FileSystemLoader(...))` +
  `env.get_template(...)` + `template.render(...)` with
  `flask.render_template(...)`, which reuses the app's cached env.

Flask's `jinja_env` already caches parsed templates in memory and
respects `TEMPLATES_AUTO_RELOAD` (tied to `app.debug`), so dev-time
template edits still hot-reload without sacrificing prod caching.

### 2. Per-request `user_settings` cache

- `app/blueprints/helpers.py`: add `get_current_user_settings()` that
  memoises on `flask.g._user_settings`; add
  `invalidate_current_user_settings()` for the write path.
- Route helpers `get_current_user_header / _section_names /
  _custom_sections` now read from the cached dict instead of each
  opening their own DB connection.
- `app/blueprints/editor.py`: `index()`, `preview()`, and
  `download_pdf()` now call `get_current_user_settings()` instead of
  `get_user_settings(user_id)` directly. The `style` dict is built via
  a new `_style_with_defaults()` helper so the default fallback logic
  lives in one place.
- `app/blueprints/cover_letter.py`: `_render_cover_letter_html()` now
  uses the cached helper (and drops its now-redundant `user_id` arg).
- `app/blueprints/settings.py`: invalidate the cache after
  `update_user_settings()` so any follow-up read in the same request
  sees the new values.

The cache is scoped to `flask.g`, which is per-request, so staleness
across requests is not a concern. The onboarding write path is
unchanged; it redirects after writing and never reads settings again in
the same request.

### 3. Inline the first preview render

- `app/blueprints/editor.py`: `index()` now calls
  `_render_resume_html(...)` once and passes the result to the
  template as `initial_preview_html`.
- `templates/editor.html`: the preview iframe now uses
  `srcdoc="{{ initial_preview_html }}"` so the browser paints the
  rendered resume from the initial HTML response -- no second
  round trip.
- `static/js/editor.js`: drop the `setTimeout(updatePreview, 200)`
  initial fetch. Instead, attach a one-shot `load` listener to the
  iframe that calls `resizePreview()` once the browser finishes
  parsing the inlined document. The existing debounced
  `updatePreview()` on editor changes is unchanged, so typing
  continues to refresh the preview as before.

Jinja auto-escaping handles the `srcdoc` attribute safely -- the HTML
gets entity-encoded on the way into the attribute and the browser
decodes it back when parsing srcdoc.

## Consequences

### Positive

- **Editor page load drops one round trip** (the 200ms-delayed
  `/api/preview` fetch) and collapses 3-4 settings queries into one.
  On Render free tier + Neon with 50-150ms RTT, that's roughly
  300-600ms off cold tab switches and ~150-400ms off warm ones.
- **Every `/api/preview` and `/api/cover_letter/preview` call is
  faster** because the Jinja env + parsed template are reused. This
  also benefits typing latency inside the editor, not just tab
  switches.
- **Render path is simpler.** One `_style_with_defaults()` helper
  replaces three copies of the same default-fallback dict.
  `_render_cover_letter_html()` no longer needs a `user_id`
  parameter.
- **No new dependencies.** Pure refactor.

### Negative

- **Per-request cache requires invalidation discipline.** If a future
  code path writes settings mid-request and then re-reads them in the
  same request, it must call `invalidate_current_user_settings()`.
  Today that path is only in `settings.api_settings` and is handled.
- **Initial preview HTML is inlined into the editor page response**,
  growing its size by the rendered resume HTML (typically a few KB).
  Cost is negligible vs. the round trip saved; the browser was going
  to fetch and parse it anyway.

### Neutral

- **`md_bold` filter is now global.** Any future template served
  through Flask can use it without registering it locally. No current
  template uses it outside `resume.html` / `cover_letter.html`, so no
  risk of name collision today.
- **Dev-time template reload** still works: Flask's `jinja_env`
  respects `TEMPLATES_AUTO_RELOAD = app.debug`, which the app factory
  already sets.

## Alternatives considered (and rejected for now)

### Option 4: Move `inject_user` to `before_request` + `g`

Every template render currently triggers a `get_user_by_id()` DB call
via the context processor in `app/__init__.py`. Moving the lookup to
a `before_request` hook that caches on `g` (and skips `/api/*` routes
that don't render templates) would save one query per render.
**Deferred** because:
- The `user` object is only referenced in a handful of templates.
- The savings stack with option 2 but are smaller in isolation.
- Worth doing together with option 5 (connection pooling) in a
  follow-up ADR focused on "DB query hygiene."

### Option 5: Connection pooling

Every `get_db()` opens a fresh psycopg2 connection. On Neon serverless
that's a TLS handshake + auth round trip -- roughly 20-80ms per query.
A `ThreadedConnectionPool` or a switch to SQLAlchemy's pool would
amortise that.
**Deferred** because:
- Touches `app/models.py` `get_db()` contract and every call site.
- Interacts with `init_db()`'s advisory-lock path (ADR 0002 operational
  notes) -- needs careful testing.
- Smaller marginal win now that settings are cached per-request.

### Option 6: SPA-style tab nav

Replacing `<a href>` links with client-side fetch + DOM swap would
avoid rebuilding the Ace editor on every tab switch and keep the
browser's parse/compile cache hot.
**Deferred** because:
- Requires a router, partial-HTML response contracts, and careful
  teardown of side panels / event handlers.
- The trio above already takes the observable lag from ~1.5s to
  roughly ~300-500ms on a warm Render instance; that's likely good
  enough for a personal tool on a free tier.
- Revisit if users still complain after this lands.

## Operational notes

- **Cold-start amplifies everything.** The first request after Render's
  15-minute sleep still eats ~30s waking the container (ADR 0002).
  This ADR doesn't help that case -- it only helps the warm path.
  The optional UptimeRobot ping from ADR 0002 is still the right
  mitigation there.
- **Cache invalidation spots to remember** if adding new write paths:
  any `update_user_settings()` call that's followed by a settings read
  in the same request must call `invalidate_current_user_settings()`.
  Grep for callers before adding.

## When to revisit

Trigger conditions that would motivate the deferred options:

1. **Tab switches still feel slow after this lands.** Ship option 6
   (SPA tab nav). Biggest remaining win on perceived latency.
2. **Any route shows >100ms in DB time under normal load.** Ship
   option 5 (connection pool) -- connection overhead dominates on
   Neon serverless.
3. **User profile rendering becomes a measurable chunk of render
   time.** Ship option 4 (`inject_user` on `g`).

## References

- [app/blueprints/editor.py](../../app/blueprints/editor.py)
- [app/blueprints/cover_letter.py](../../app/blueprints/cover_letter.py)
- [app/blueprints/helpers.py](../../app/blueprints/helpers.py)
- [app/__init__.py](../../app/__init__.py)
- [templates/editor.html](../../templates/editor.html)
- [static/js/editor.js](../../static/js/editor.js)
- Deploy context: [ADR 0002](0002-deploy-on-render-free-tier.md)
  (Render free tier + Neon latency profile).
