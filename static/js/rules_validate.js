/**
 * Rules validate -- adds a "Check rules" button and an issues panel to the
 * resume_rules / cover_letter_rules editor pages.
 *
 * Flow:
 *   1. Inject a "Check rules" button into the toolbar (right side, before Save).
 *   2. On click, POST the current Ace editor value to
 *      /api/databases/<db_type>/validate. Render the verdict as a panel
 *      inserted between the toggles row and the split editor.
 *   3. Wrap window.saveContent (which rules_toggles.js has already replaced)
 *      so that saving with an active reject-severity issue triggers a confirm()
 *      dialog. Warns are advisory only.
 *   4. If the endpoint returns 400 about API keys, show a muted info card so
 *      the user knows where to fix it. Save always proceeds.
 *
 * Depends on the global `_editor` set by databases.js's initDatabaseEditor,
 * and the `showToast` helper from toast.js. Vanilla JS, no frameworks.
 */

(function () {
    window.initRulesValidate = function (dbType) {
        injectButton(dbType);
        wrapSaveContent();
    };

    // --- State ------------------------------------------------------------

    // Last-known severity set currently rendered in the panel. Reset to []
    // whenever the panel is dismissed, re-rendered, or the user runs a new
    // validation. Used by the save wrapper to decide whether to gate.
    var _currentIssues = [];

    function hasRejectIssue() {
        for (var i = 0; i < _currentIssues.length; i++) {
            if (_currentIssues[i] && _currentIssues[i].severity === 'reject') {
                return true;
            }
        }
        return false;
    }

    // --- Button injection -------------------------------------------------

    function injectButton(dbType) {
        var right = document.querySelector('.db-toolbar-right');
        if (!right) return;

        var btn = document.createElement('button');
        btn.type = 'button';
        btn.id = 'rv-check-btn';
        btn.className = 'btn btn-secondary';
        btn.textContent = 'Check rules';

        // Place before the Save button so the order is: save-status, Check, Save.
        var saveBtn = right.querySelector('button.btn-primary');
        if (saveBtn) {
            right.insertBefore(btn, saveBtn);
        } else {
            right.appendChild(btn);
        }

        btn.addEventListener('click', function () {
            runValidation(dbType, btn);
        });
    }

    // --- Request ----------------------------------------------------------

    function runValidation(dbType, btn) {
        if (typeof _editor === 'undefined' || !_editor) {
            if (typeof showToast === 'function') {
                showToast('Editor not ready', 'error');
            }
            return;
        }

        var content = _editor.getValue();
        setButtonLoading(btn, true);

        fetch('/api/databases/' + dbType + '/validate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content: content }),
        })
            .then(function (r) {
                return r.json().then(function (data) {
                    return { ok: r.ok, status: r.status, data: data };
                });
            })
            .then(function (res) {
                if (res.ok) {
                    renderVerdict(res.data);
                } else if (res.status === 400 && isApiKeyError(res.data)) {
                    renderApiKeyFallback();
                } else {
                    var msg = (res.data && res.data.error) || 'Validation failed';
                    if (typeof showToast === 'function') showToast(msg, 'error');
                }
            })
            .catch(function () {
                if (typeof showToast === 'function') {
                    showToast('Validation failed', 'error');
                }
            })
            .then(function () {
                setButtonLoading(btn, false);
            });
    }

    function isApiKeyError(data) {
        if (!data || !data.error) return false;
        var msg = String(data.error).toLowerCase();
        return msg.indexOf('api key') !== -1 || msg.indexOf('api_key') !== -1;
    }

    function setButtonLoading(btn, loading) {
        if (!btn) return;
        if (loading) {
            btn.disabled = true;
            btn.innerHTML = '<span class="rv-spinner" aria-hidden="true"></span>Checking...';
        } else {
            btn.disabled = false;
            btn.textContent = 'Check rules';
        }
    }

    // --- Rendering --------------------------------------------------------

    function getPanel() {
        var existing = document.getElementById('rv-panel');
        if (existing) return existing;

        var panel = document.createElement('div');
        panel.id = 'rv-panel';
        panel.className = 'rv-panel';

        // Insert after the toggles row (or the toolbar as a fallback) and
        // before the split editor, matching: toolbar -> toggles -> panel -> split.
        var container = document.querySelector('.db-editor-container');
        var split = container ? container.querySelector('.db-split') : null;
        var toggles = document.getElementById('rules-toggles');
        if (container && split) {
            container.insertBefore(panel, split);
        } else if (toggles && toggles.parentNode) {
            toggles.parentNode.insertBefore(panel, toggles.nextSibling);
        } else {
            document.body.appendChild(panel);
        }
        return panel;
    }

    function dismissPanel() {
        _currentIssues = [];
        var panel = document.getElementById('rv-panel');
        if (panel && panel.parentNode) {
            panel.parentNode.removeChild(panel);
        }
    }

    function renderVerdict(data) {
        var relevant = !!data.relevant;
        var issues = Array.isArray(data.issues) ? data.issues : [];
        var summary = data.summary || '';
        _currentIssues = issues.slice();

        var panel = getPanel();
        panel.innerHTML = '';
        panel.appendChild(renderHeader(summary));

        var cards = document.createElement('div');
        cards.className = 'rv-cards';

        if (relevant && issues.length === 0) {
            cards.appendChild(renderOkCard(summary || 'Looks good -- no issues found.'));
        } else {
            issues.forEach(function (issue) {
                cards.appendChild(renderIssueCard(issue));
            });
        }

        panel.appendChild(cards);
    }

    function renderApiKeyFallback() {
        _currentIssues = [];
        var panel = getPanel();
        panel.innerHTML = '';
        panel.appendChild(renderHeader(''));

        var cards = document.createElement('div');
        cards.className = 'rv-cards';

        var card = document.createElement('div');
        card.className = 'rv-card rv-card-info';
        card.textContent = 'Set an API key in Settings to enable rules validation.';
        cards.appendChild(card);

        panel.appendChild(cards);
    }

    function renderHeader(summary) {
        var wrap = document.createElement('div');
        wrap.className = 'rv-header';

        var sum = document.createElement('div');
        sum.className = 'rv-summary';
        sum.textContent = summary || '';
        wrap.appendChild(sum);

        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-secondary btn-sm rv-dismiss';
        btn.textContent = 'Dismiss';
        btn.addEventListener('click', dismissPanel);
        wrap.appendChild(btn);

        return wrap;
    }

    function renderOkCard(text) {
        var card = document.createElement('div');
        card.className = 'rv-card rv-card-ok';
        card.textContent = text;
        return card;
    }

    function renderIssueCard(issue) {
        var sev = issue && issue.severity === 'reject' ? 'reject' : 'warn';
        var card = document.createElement('div');
        card.className = 'rv-card rv-card-' + sev;

        var tag = document.createElement('span');
        tag.className = 'rv-sev rv-sev-' + sev;
        tag.textContent = sev;
        card.appendChild(tag);

        if (issue && issue.snippet) {
            var snip = document.createElement('div');
            snip.className = 'rv-snippet';
            snip.textContent = String(issue.snippet);
            card.appendChild(snip);
        }

        if (issue && issue.reason) {
            var reason = document.createElement('div');
            reason.className = 'rv-reason';
            var rlabel = document.createElement('strong');
            rlabel.textContent = 'Why: ';
            reason.appendChild(rlabel);
            reason.appendChild(document.createTextNode(String(issue.reason)));
            card.appendChild(reason);
        }

        if (issue && issue.suggestion) {
            var sug = document.createElement('div');
            sug.className = 'rv-suggestion';
            var slabel = document.createElement('strong');
            slabel.textContent = 'Suggestion: ';
            sug.appendChild(slabel);
            sug.appendChild(document.createTextNode(String(issue.suggestion)));
            card.appendChild(sug);
        }

        return card;
    }

    // --- Save gate --------------------------------------------------------

    function wrapSaveContent() {
        // IMPORTANT: rules_toggles.js replaces window.saveContent on a timer
        // after the editor comes up. Wait until its override lands before we
        // wrap, otherwise the toggles replacement would clobber our wrapper.
        var start = Date.now();
        var poll = setInterval(function () {
            if (typeof _editor !== 'undefined' && _editor && typeof window.saveContent === 'function') {
                clearInterval(poll);
                installWrapper();
            } else if (Date.now() - start > 5000) {
                // Editor never came up; install best-effort so the button
                // at least stays functional if save is ever wired manually.
                clearInterval(poll);
                if (typeof window.saveContent === 'function') installWrapper();
            }
        }, 80);
    }

    function installWrapper() {
        var prior = window.saveContent;
        window.saveContent = function () {
            if (hasRejectIssue()) {
                var ok = window.confirm(
                    "This document has issues flagged as 'reject'. Save anyway?"
                );
                if (!ok) return;
            }
            return prior.apply(this, arguments);
        };
    }
})();
