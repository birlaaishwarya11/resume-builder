/**
 * Rules toggles -- renders a compact row of configurable options above the
 * markdown editor on resume_rules / cover_letter_rules pages.
 *
 * Storage model (client-side only -- the backend contract is unchanged):
 *   A fenced JSON marker block is prepended to the markdown document on save:
 *
 *     <!-- toggles:json -->
 *     ```json
 *     { ... }
 *     ```
 *     <!-- /toggles -->
 *
 *   On load we parse that block out of the document, hydrate the toggle UI,
 *   and put the remaining body into the Ace editor. On save we re-emit the
 *   marker block prepended to the editor body and PUT to /api/databases/<type>.
 *
 * This file REPLACES the default initDatabaseEditor() flow in databases.js --
 * the Ace editor is still created by initDatabaseEditor(), but we intercept
 * load/save and re-route content through the toggles layer.
 */

(function () {
    // Exposed entry point. Called from the rules template AFTER the editor is
    // initialised via initDatabaseEditor(dbType).
    window.initRulesToggles = function (dbType) {
        var schema = getSchemaFor(dbType);
        if (!schema) return;

        renderToggles(dbType, schema);

        // Wait for the Ace editor that databases.js created and rewire it.
        var waitReady = setInterval(function () {
            if (typeof _editor !== 'undefined' && _editor) {
                clearInterval(waitReady);
                rewireEditor(dbType, schema);
            }
        }, 50);
    };

    // --- Marker constants --------------------------------------------------

    var MARKER_OPEN = '<!-- toggles:json -->';
    var MARKER_CLOSE = '<!-- /toggles -->';
    // Matches: <!-- toggles:json -->\n```json\n{...}\n```\n<!-- /toggles -->\n?
    var MARKER_RE = /^<!-- toggles:json -->\n```json\n([\s\S]*?)\n```\n<!-- \/toggles -->\n?/;

    // --- Toggle schema -----------------------------------------------------

    // Full registry keyed by toggle id. `types` lists which rules pages show it.
    var TOGGLES = {
        tone: {
            label: 'Tone',
            kind: 'radio',
            options: [
                { value: 'confident', label: 'Confident' },
                { value: 'humble', label: 'Humble' },
                { value: 'neutral', label: 'Neutral' },
            ],
            default: 'neutral',
            types: ['resume_rules', 'cover_letter_rules'],
        },
        bullets_per_role: {
            label: 'Bullets per role',
            kind: 'number',
            min: 2,
            max: 7,
            default: 4,
            types: ['resume_rules'],
        },
        cover_letter_length: {
            label: 'Cover letter length',
            kind: 'radio',
            options: [
                { value: 'short', label: 'Short (3 paragraphs)' },
                { value: 'standard', label: 'Standard (4 paragraphs)' },
            ],
            default: 'standard',
            types: ['cover_letter_rules'],
        },
        use_abbreviations: {
            label: 'Use abbreviations',
            kind: 'checkbox',
            default: false,
            defaultsByType: { resume_rules: true, cover_letter_rules: false },
            types: ['resume_rules', 'cover_letter_rules'],
        },
        em_dash_policy: {
            label: 'Em-dash policy',
            kind: 'radio',
            options: [
                { value: 'forbid', label: 'Forbid' },
                { value: 'allow', label: 'Allow' },
            ],
            default: 'forbid',
            types: ['resume_rules', 'cover_letter_rules'],
        },
        show_gpa: {
            label: 'Show GPA',
            kind: 'checkbox',
            default: true,
            types: ['resume_rules'],
        },
        project_count: {
            label: 'Project count',
            kind: 'number',
            min: 2,
            max: 5,
            default: 3,
            types: ['resume_rules'],
        },
    };

    // Visibility + order per rules page.
    var ORDER = {
        resume_rules: [
            'tone', 'bullets_per_role', 'use_abbreviations',
            'em_dash_policy', 'show_gpa', 'project_count',
        ],
        cover_letter_rules: [
            'tone', 'cover_letter_length', 'use_abbreviations', 'em_dash_policy',
        ],
    };

    function getSchemaFor(dbType) {
        var ids = ORDER[dbType];
        if (!ids) return null;
        return ids.map(function (id) {
            return Object.assign({ id: id }, TOGGLES[id]);
        });
    }

    function defaultsFor(dbType, schema) {
        var out = {};
        schema.forEach(function (t) {
            if (t.defaultsByType && Object.prototype.hasOwnProperty.call(t.defaultsByType, dbType)) {
                out[t.id] = t.defaultsByType[dbType];
            } else {
                out[t.id] = t.default;
            }
        });
        return out;
    }

    // --- UI ---------------------------------------------------------------

    function renderToggles(dbType, schema) {
        var mount = document.getElementById('rules-toggles');
        if (!mount) return;

        var html = [];
        html.push('<div class="rt-header">');
        html.push('<span class="rt-title">Rules Toggles</span>');
        html.push('<button type="button" class="btn btn-secondary btn-sm" id="rt-reset">Reset to defaults</button>');
        html.push('</div>');
        html.push('<div class="rt-grid">');

        schema.forEach(function (t) {
            html.push('<div class="rt-item" data-toggle-id="' + t.id + '">');
            html.push('<div class="rt-label">' + escapeHtml(t.label) + '</div>');
            html.push('<div class="rt-control">' + renderControl(t) + '</div>');
            html.push('</div>');
        });

        html.push('</div>');
        mount.innerHTML = html.join('');

        var resetBtn = document.getElementById('rt-reset');
        if (resetBtn) {
            resetBtn.addEventListener('click', function () {
                applyState(schema, defaultsFor(dbType, schema));
            });
        }
    }

    function renderControl(t) {
        if (t.kind === 'radio') {
            return t.options.map(function (opt, i) {
                var id = 'rt-' + t.id + '-' + opt.value;
                return (
                    '<label class="rt-radio" for="' + id + '">' +
                    '<input type="radio" id="' + id + '" name="rt-' + t.id + '" ' +
                    'value="' + escapeAttr(opt.value) + '"' + (i === 0 ? ' checked' : '') + '>' +
                    '<span>' + escapeHtml(opt.label) + '</span>' +
                    '</label>'
                );
            }).join('');
        }
        if (t.kind === 'checkbox') {
            var cid = 'rt-' + t.id;
            return (
                '<label class="rt-check" for="' + cid + '">' +
                '<input type="checkbox" id="' + cid + '">' +
                '<span class="rt-check-state">off</span>' +
                '</label>'
            );
        }
        if (t.kind === 'number') {
            var nid = 'rt-' + t.id;
            return (
                '<input type="number" id="' + nid + '" class="rt-number" ' +
                'min="' + t.min + '" max="' + t.max + '" step="1" value="' + t.default + '">'
            );
        }
        return '';
    }

    function readState(schema) {
        var state = {};
        schema.forEach(function (t) {
            if (t.kind === 'radio') {
                var el = document.querySelector('input[name="rt-' + t.id + '"]:checked');
                state[t.id] = el ? el.value : t.default;
            } else if (t.kind === 'checkbox') {
                var cb = document.getElementById('rt-' + t.id);
                state[t.id] = !!(cb && cb.checked);
            } else if (t.kind === 'number') {
                var n = document.getElementById('rt-' + t.id);
                var v = n ? parseInt(n.value, 10) : t.default;
                if (isNaN(v)) v = t.default;
                if (v < t.min) v = t.min;
                if (v > t.max) v = t.max;
                state[t.id] = v;
            }
        });
        return state;
    }

    function applyState(schema, state) {
        schema.forEach(function (t) {
            var v = Object.prototype.hasOwnProperty.call(state, t.id) ? state[t.id] : t.default;
            if (t.kind === 'radio') {
                var radios = document.querySelectorAll('input[name="rt-' + t.id + '"]');
                var matched = false;
                radios.forEach(function (r) {
                    if (r.value === v) { r.checked = true; matched = true; }
                });
                if (!matched && radios[0]) radios[0].checked = true;
            } else if (t.kind === 'checkbox') {
                var cb = document.getElementById('rt-' + t.id);
                if (cb) {
                    cb.checked = !!v;
                    updateCheckLabel(cb);
                }
            } else if (t.kind === 'number') {
                var n = document.getElementById('rt-' + t.id);
                if (n) n.value = String(v);
            }
        });
        // Re-bind the checkbox state label refreshers each time.
        bindCheckboxLabels();
    }

    function bindCheckboxLabels() {
        var boxes = document.querySelectorAll('#rules-toggles input[type="checkbox"]');
        boxes.forEach(function (cb) {
            updateCheckLabel(cb);
            if (!cb._rtBound) {
                cb.addEventListener('change', function () { updateCheckLabel(cb); });
                cb._rtBound = true;
            }
        });
    }

    function updateCheckLabel(cb) {
        var lbl = cb.parentElement && cb.parentElement.querySelector('.rt-check-state');
        if (lbl) lbl.textContent = cb.checked ? 'on' : 'off';
    }

    // --- Editor wiring ----------------------------------------------------

    function rewireEditor(dbType, schema) {
        // databases.js already kicked off the fetch + setValue. We need to
        // re-fetch (cheap) so we can split toggles off before showing the body.
        fetch('/api/databases/' + dbType)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var raw = data.content || '';
                var parsed = parseDocument(raw);
                var state = Object.assign(defaultsFor(dbType, schema), parsed.toggles || {});
                applyState(schema, state);
                _editor.setValue(parsed.body, -1);
                if (typeof updatePreview === 'function') updatePreview();
            })
            .catch(function () {
                // Fall back to defaults on parse/network failure; body stays as
                // whatever databases.js already loaded.
                applyState(schema, defaultsFor(dbType, schema));
            });

        // Override saveContent so the toggle marker is prepended on every PUT.
        window.saveContent = function () {
            var status = document.getElementById('save-status');
            if (status) status.textContent = 'Saving...';

            var body = _editor.getValue();
            var state = readState(schema);
            var payload = serializeDocument(state, body);

            fetch('/api/databases/' + dbType, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: payload }),
            })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (data.status === 'ok') {
                        if (status) {
                            status.textContent = 'Saved';
                            setTimeout(function () { status.textContent = ''; }, 2000);
                        }
                        if (typeof showToast === 'function') showToast('Saved', 'success');
                    } else {
                        if (status) status.textContent = 'Error';
                        if (typeof showToast === 'function') showToast(data.error || 'Save failed', 'error');
                    }
                })
                .catch(function () {
                    if (status) status.textContent = 'Error';
                    if (typeof showToast === 'function') showToast('Save failed', 'error');
                });
        };
    }

    // --- Serialisation ----------------------------------------------------

    function parseDocument(raw) {
        var m = raw.match(MARKER_RE);
        if (!m) return { toggles: null, body: raw };
        var jsonText = m[1];
        var body = raw.slice(m[0].length);
        try {
            var toggles = JSON.parse(jsonText);
            if (toggles && typeof toggles === 'object') {
                return { toggles: toggles, body: body };
            }
        } catch (_e) { /* fall through */ }
        return { toggles: null, body: raw };
    }

    function serializeDocument(state, body) {
        var json = JSON.stringify(state, null, 2);
        return MARKER_OPEN + '\n```json\n' + json + '\n```\n' + MARKER_CLOSE + '\n' + body;
    }

    // --- Utils ------------------------------------------------------------

    function escapeHtml(s) {
        var d = document.createElement('div');
        d.textContent = String(s == null ? '' : s);
        return d.innerHTML;
    }
    function escapeAttr(s) {
        return escapeHtml(s).replace(/"/g, '&quot;');
    }
})();
