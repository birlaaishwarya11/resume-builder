/**
 * Database Builder wizard -- vanilla JS, no framework.
 *
 * State lives on window.dbbState so it's easy to inspect during debugging.
 * All API calls funnel through dbbFetchJson() which surfaces errors via showToast.
 */

(function () {
    // Global wizard state.
    var state = {
        step: 1,
        items: [],            // accumulated resume items
        moments: [],          // accumulated cover-letter moments
        expanded: {},         // row id -> bool (for review expand/collapse)
        questions: [],        // loaded from /api/db_builder/questions
        budgetLimits: null,   // fetches / llm_calls / bytes_in
        latestBudget: null,   // last reported usage from any API call
        candidateMd: '',
        coverLetterMd: '',
        questionsLoaded: false,
    };
    window.dbbState = state;

    // --- Init ---------------------------------------------------------------

    window.dbbInit = function () {
        dbbRenderStep(1);
        dbbRenderBudget();
    };

    // --- Step navigation ----------------------------------------------------

    window.dbbGoToStep = function (n) {
        if (n === 2 && !state.questionsLoaded) {
            dbbLoadQuestions();
        }
        if (n === 3) {
            dbbRenderReview();
        }
        dbbRenderStep(n);
    };

    function dbbRenderStep(n) {
        state.step = n;
        for (var i = 1; i <= 3; i++) {
            var section = document.getElementById('dbb-step-' + i);
            if (section) section.hidden = (i !== n);

            var dot = document.getElementById('dbb-dot-' + i);
            var lbl = document.getElementById('dbb-label-' + i);
            if (dot) {
                dot.classList.remove('active', 'done');
                if (i < n) dot.classList.add('done');
                else if (i === n) dot.classList.add('active');
            }
            if (lbl) {
                lbl.classList.remove('active', 'done');
                if (i < n) lbl.classList.add('done');
                else if (i === n) lbl.classList.add('active');
            }
        }
        for (var j = 1; j <= 2; j++) {
            var line = document.getElementById('dbb-line-' + j);
            if (line) {
                line.classList.remove('done');
                if (j < n) line.classList.add('done');
            }
        }
        // Scroll to top of wizard on step change so users see the new card.
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    // --- Budget display -----------------------------------------------------

    function dbbRenderBudget() {
        var el = document.getElementById('dbb-budget-text');
        if (!el) return;
        var used = state.latestBudget;
        var limits = state.budgetLimits;
        if (!used && !limits) {
            el.textContent = 'not started';
            return;
        }
        var parts = [];
        if (used && limits) {
            parts.push('fetches ' + (used.fetches || 0) + '/' + limits.fetches);
            parts.push('LLM calls ' + (used.llm_calls || 0) + '/' + limits.llm_calls);
            var bytesKb = Math.round((used.bytes_in || 0) / 1024);
            var limitKb = Math.round(limits.bytes_in / 1024);
            parts.push('input ' + bytesKb + ' KB / ' + limitKb + ' KB');
        } else if (limits) {
            parts.push('fetches 0/' + limits.fetches);
            parts.push('LLM calls 0/' + limits.llm_calls);
        } else if (used) {
            parts.push('fetches ' + (used.fetches || 0));
            parts.push('LLM calls ' + (used.llm_calls || 0));
        }
        el.textContent = parts.join(' · ');
    }

    // --- Step 1: project URL rows ------------------------------------------

    window.dbbAddProjectUrl = function () {
        var list = document.getElementById('dbb-project-urls');
        var row = document.createElement('div');
        row.className = 'dbb-url-row';
        var input = document.createElement('input');
        input.type = 'url';
        input.className = 'dbb-project-url-input';
        input.placeholder = 'https://github.com/you/project';
        input.setAttribute('aria-label', 'Project URL');
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-secondary btn-sm dbb-remove-url';
        btn.textContent = 'Remove';
        btn.setAttribute('aria-label', 'Remove this URL');
        btn.onclick = function () { dbbRemoveProjectUrl(btn); };
        row.appendChild(input);
        row.appendChild(btn);
        list.appendChild(row);
        input.focus();
    };

    window.dbbRemoveProjectUrl = function (btn) {
        var list = document.getElementById('dbb-project-urls');
        var row = btn.closest('.dbb-url-row');
        if (!row) return;
        if (list.querySelectorAll('.dbb-url-row').length <= 1) {
            // Keep at least one row; just clear its value.
            var input = row.querySelector('input');
            if (input) input.value = '';
            return;
        }
        row.remove();
    };

    // --- Step 1: extract ----------------------------------------------------

    window.dbbRunExtract = function () {
        var portfolioUrl = (document.getElementById('dbb-portfolio-url').value || '').trim();
        var projectUrlInputs = document.querySelectorAll('.dbb-project-url-input');
        var projectUrls = [];
        projectUrlInputs.forEach(function (inp) {
            var v = (inp.value || '').trim();
            if (v) projectUrls.push(v);
        });
        var githubPat = (document.getElementById('dbb-github-pat').value || '').trim();

        if (!portfolioUrl && projectUrls.length === 0) {
            showToast('Add a portfolio URL or at least one project URL.', 'error');
            return;
        }

        var body = {};
        if (portfolioUrl) body.portfolio_url = portfolioUrl;
        if (projectUrls.length) body.project_urls = projectUrls;
        if (githubPat) body.github_pat = githubPat;

        dbbSetExtractBusy(true);
        dbbFetchJson('/api/db_builder/extract', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        }).then(function (data) {
            dbbSetExtractBusy(false);
            if (!data) return;
            if (Array.isArray(data.items)) {
                state.items = state.items.concat(data.items.map(dbbNormalizeRow));
            }
            if (Array.isArray(data.moments)) {
                state.moments = state.moments.concat(data.moments.map(dbbNormalizeRow));
            }
            if (data.budget) {
                state.latestBudget = data.budget;
                dbbRenderBudget();
            }
            dbbRenderLogs(data.logs || []);
            var added = (data.items || []).length + ' items, ' +
                        (data.moments || []).length + ' moments';
            showToast('Extraction done: ' + added, 'success');
            dbbGoToStep(2);
        }).catch(function () {
            dbbSetExtractBusy(false);
        });
    };

    function dbbSetExtractBusy(busy) {
        var btn = document.getElementById('dbb-run-extract');
        var spinner = document.getElementById('dbb-extract-spinner');
        var label = document.getElementById('dbb-extract-label');
        if (!btn) return;
        btn.disabled = !!busy;
        if (spinner) spinner.hidden = !busy;
        if (label) label.textContent = busy ? 'Extracting...' : 'Run extraction';
    }

    function dbbRenderLogs(logs) {
        var wrap = document.getElementById('dbb-log-wrap');
        var pre = document.getElementById('dbb-log-content');
        if (!wrap || !pre) return;
        if (!logs || !logs.length) {
            wrap.hidden = true;
            pre.textContent = '';
            return;
        }
        wrap.hidden = false;
        pre.textContent = logs.map(function (l) {
            if (typeof l === 'string') return l;
            try { return JSON.stringify(l); } catch (e) { return String(l); }
        }).join('\n');
    }

    // --- Step 2: questions --------------------------------------------------

    function dbbLoadQuestions() {
        dbbFetchJson('/api/db_builder/questions', { method: 'GET' })
            .then(function (data) {
                if (!data) return;
                state.questions = data.questions || [];
                if (data.budget) {
                    state.budgetLimits = data.budget;
                    dbbRenderBudget();
                }
                state.questionsLoaded = true;
                dbbRenderQuestions();
                dbbUpdateAccumCount();
            });
    }

    function dbbRenderQuestions() {
        var container = document.getElementById('dbb-questions-list');
        if (!container) return;
        container.innerHTML = '';
        state.questions.forEach(function (q) {
            var wrap = document.createElement('div');
            wrap.className = 'dbb-question';
            wrap.id = 'dbb-q-' + q.id;

            var prompt = document.createElement('label');
            prompt.className = 'dbb-question-prompt';
            prompt.setAttribute('for', 'dbb-ta-' + q.id);
            prompt.textContent = q.prompt;
            wrap.appendChild(prompt);

            var why = document.createElement('div');
            why.className = 'dbb-question-why';
            why.textContent = q.why;
            wrap.appendChild(why);

            var ta = document.createElement('textarea');
            ta.id = 'dbb-ta-' + q.id;
            ta.setAttribute('data-qid', q.id);
            ta.placeholder = 'Type your answer here (or skip)';
            wrap.appendChild(ta);

            var foot = document.createElement('div');
            foot.className = 'dbb-question-footer';
            var status = document.createElement('div');
            status.className = 'dbb-q-status';
            status.id = 'dbb-q-status-' + q.id;
            status.textContent = '';
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn btn-secondary btn-sm';
            btn.textContent = 'Extract this answer';
            btn.onclick = function () { dbbAnswerQuestion(q.id); };
            foot.appendChild(status);
            foot.appendChild(btn);
            wrap.appendChild(foot);

            container.appendChild(wrap);
        });
    }

    window.dbbAnswerQuestion = function (qid) {
        var ta = document.getElementById('dbb-ta-' + qid);
        if (!ta) return;
        var answer = (ta.value || '').trim();
        if (!answer) {
            showToast('Nothing to extract -- the answer is empty.', 'error');
            return;
        }
        var status = document.getElementById('dbb-q-status-' + qid);
        if (status) {
            status.textContent = 'Extracting...';
            status.style.color = '#888';
        }

        dbbFetchJson('/api/db_builder/answer', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question_id: qid, answer: answer }),
        }).then(function (data) {
            if (!data) {
                if (status) { status.textContent = ''; }
                return;
            }
            var addedItems = (data.items || []).length;
            var addedMoments = (data.moments || []).length;
            if (Array.isArray(data.items)) state.items = state.items.concat(data.items.map(dbbNormalizeRow));
            if (Array.isArray(data.moments)) state.moments = state.moments.concat(data.moments.map(dbbNormalizeRow));
            if (data.budget) {
                state.latestBudget = data.budget;
                dbbRenderBudget();
            }
            if (status) {
                status.textContent = '+' + addedItems + ' items, +' + addedMoments + ' moments';
                status.style.color = '#2e7d32';
            }
            dbbUpdateAccumCount();
        }).catch(function () {
            if (status) { status.textContent = ''; }
        });
    };

    function dbbUpdateAccumCount() {
        var el = document.getElementById('dbb-accum-count');
        if (!el) return;
        el.textContent = state.items.length + ' items, ' + state.moments.length + ' moments';
    }

    // --- Step 3: review -----------------------------------------------------

    function dbbRenderReview() {
        dbbRenderItems();
        dbbRenderMoments();
        dbbUpdateReviewCounts();
    }

    function dbbUpdateReviewCounts() {
        dbbRenderListCount('dbb-items-count', state.items, 'item');
        dbbRenderListCount('dbb-moments-count', state.moments, 'moment');
    }

    function dbbRenderListCount(elId, rows, kind) {
        var el = document.getElementById(elId);
        if (!el) return;
        var total = rows.length;
        var flagged = 0;
        var included = 0;
        rows.forEach(function (r) {
            if (r && r.on_topic === false) flagged++;
            if (r && r.include) included++;
        });
        var noun = kind === 'item' ? 'item' : 'moment';
        var plural = total === 1 ? noun : noun + 's';
        el.textContent = total + ' ' + plural + ' · ' +
            flagged + ' flagged · ' +
            included + ' will be saved';
    }

    function dbbRenderItems() {
        var container = document.getElementById('dbb-items-list');
        if (!container) return;
        container.innerHTML = '';
        if (state.items.length === 0) {
            var empty = document.createElement('div');
            empty.className = 'dbb-list-empty';
            empty.textContent = 'No items yet. Go back to Step 1 or 2 to add some.';
            container.appendChild(empty);
            return;
        }
        state.items.forEach(function (it, idx) {
            container.appendChild(dbbBuildItemRow(it, idx));
        });
    }

    function dbbRenderMoments() {
        var container = document.getElementById('dbb-moments-list');
        if (!container) return;
        container.innerHTML = '';
        if (state.moments.length === 0) {
            var empty = document.createElement('div');
            empty.className = 'dbb-list-empty';
            empty.textContent = 'No moments yet. Go back to Step 1 or 2 to add some.';
            container.appendChild(empty);
            return;
        }
        state.moments.forEach(function (m, idx) {
            container.appendChild(dbbBuildMomentRow(m, idx));
        });
    }

    function dbbBuildItemRow(item, idx) {
        var rowId = 'item-' + idx;
        var row = document.createElement('div');
        row.className = 'dbb-list-row';
        if (item.on_topic === false) row.classList.add('dbb-flagged');

        var head = document.createElement('div');
        head.className = 'dbb-list-row-head';
        head.setAttribute('role', 'button');
        head.setAttribute('tabindex', '0');
        head.onclick = function () { dbbToggleExpand(rowId, row, item, 'item'); };
        head.onkeydown = function (e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                dbbToggleExpand(rowId, row, item, 'item');
            }
        };

        var main = document.createElement('div');
        main.className = 'dbb-list-row-main';
        var title = document.createElement('div');
        title.className = 'dbb-list-row-title';
        title.textContent = item.title || '(untitled)';
        if (item.on_topic === false) {
            title.appendChild(dbbBuildFlagBadge());
        }
        main.appendChild(title);

        var metaBits = [];
        if (item.kind) metaBits.push(item.kind);
        if (item.org) metaBits.push(item.org);
        if (item.role) metaBits.push(item.role);
        var dateStr = dbbFormatDate(item.date_year, item.date_month);
        if (dateStr) metaBits.push(dateStr);
        if (metaBits.length) {
            var meta = document.createElement('div');
            meta.className = 'dbb-list-row-meta';
            meta.textContent = metaBits.join(' · ');
            main.appendChild(meta);
        }
        head.appendChild(main);

        head.appendChild(dbbBuildIncludeToggle(item, 'item', idx));

        var removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'btn btn-secondary btn-sm';
        removeBtn.textContent = 'Remove';
        removeBtn.setAttribute('aria-label', 'Remove item: ' + (item.title || 'untitled'));
        removeBtn.onclick = function (e) {
            e.stopPropagation();
            dbbRemoveItem(idx);
        };
        head.appendChild(removeBtn);

        row.appendChild(head);

        if (state.expanded[rowId]) {
            row.appendChild(dbbBuildItemBody(item));
        }
        return row;
    }

    function dbbBuildItemBody(item) {
        var body = document.createElement('div');
        body.className = 'dbb-list-row-body';

        if (item.on_topic === false && item.topic_reason) {
            var reason = document.createElement('div');
            reason.className = 'dbb-topic-reason';
            reason.textContent = item.topic_reason;
            body.appendChild(reason);
        }

        if (item.summary) {
            var p = document.createElement('div');
            p.className = 'dbb-kv';
            p.textContent = item.summary;
            body.appendChild(p);
        }
        if (Array.isArray(item.bullets) && item.bullets.length) {
            var ul = document.createElement('ul');
            item.bullets.forEach(function (b) {
                var li = document.createElement('li');
                li.textContent = b;
                ul.appendChild(li);
            });
            body.appendChild(ul);
        }
        if (Array.isArray(item.tech) && item.tech.length) {
            var t = document.createElement('div');
            t.className = 'dbb-kv';
            var s = document.createElement('strong');
            s.textContent = 'Tech: ';
            t.appendChild(s);
            t.appendChild(document.createTextNode(item.tech.join(', ')));
            body.appendChild(t);
        }
        if (item.url) {
            var u = document.createElement('div');
            u.className = 'dbb-kv';
            var sl = document.createElement('strong');
            sl.textContent = 'URL: ';
            u.appendChild(sl);
            var a = document.createElement('a');
            a.href = dbbSafeUrl(item.url);
            a.textContent = item.url;
            a.target = '_blank';
            a.rel = 'noopener noreferrer';
            u.appendChild(a);
            body.appendChild(u);
        }
        if (typeof item.confidence !== 'undefined' && item.confidence !== null) {
            var c = document.createElement('div');
            c.className = 'dbb-kv text-muted text-sm';
            c.textContent = 'Confidence: ' + item.confidence;
            body.appendChild(c);
        }
        return body;
    }

    function dbbBuildMomentRow(moment, idx) {
        var rowId = 'moment-' + idx;
        var row = document.createElement('div');
        row.className = 'dbb-list-row';
        if (moment.on_topic === false) row.classList.add('dbb-flagged');

        var head = document.createElement('div');
        head.className = 'dbb-list-row-head';
        head.setAttribute('role', 'button');
        head.setAttribute('tabindex', '0');
        head.onclick = function () { dbbToggleExpand(rowId, row, moment, 'moment'); };
        head.onkeydown = function (e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                dbbToggleExpand(rowId, row, moment, 'moment');
            }
        };

        var main = document.createElement('div');
        main.className = 'dbb-list-row-main';
        var title = document.createElement('div');
        title.className = 'dbb-list-row-title';
        title.textContent = moment.title || '(untitled)';
        if (moment.on_topic === false) {
            title.appendChild(dbbBuildFlagBadge());
        }
        main.appendChild(title);

        var metaBits = [];
        if (moment.kind) metaBits.push(moment.kind);
        if (Array.isArray(moment.themes) && moment.themes.length) {
            metaBits.push(moment.themes.join(', '));
        }
        if (metaBits.length) {
            var meta = document.createElement('div');
            meta.className = 'dbb-list-row-meta';
            meta.textContent = metaBits.join(' · ');
            main.appendChild(meta);
        }
        head.appendChild(main);

        head.appendChild(dbbBuildIncludeToggle(moment, 'moment', idx));

        var removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'btn btn-secondary btn-sm';
        removeBtn.textContent = 'Remove';
        removeBtn.setAttribute('aria-label', 'Remove moment: ' + (moment.title || 'untitled'));
        removeBtn.onclick = function (e) {
            e.stopPropagation();
            dbbRemoveMoment(idx);
        };
        head.appendChild(removeBtn);

        row.appendChild(head);

        if (state.expanded[rowId]) {
            row.appendChild(dbbBuildMomentBody(moment));
        }
        return row;
    }

    function dbbBuildMomentBody(moment) {
        var body = document.createElement('div');
        body.className = 'dbb-list-row-body';
        if (moment.on_topic === false && moment.topic_reason) {
            var reason = document.createElement('div');
            reason.className = 'dbb-topic-reason';
            reason.textContent = moment.topic_reason;
            body.appendChild(reason);
        }
        if (moment.narrative) {
            var p = document.createElement('div');
            p.className = 'dbb-kv';
            p.textContent = moment.narrative;
            body.appendChild(p);
        }
        if (moment.url) {
            var u = document.createElement('div');
            u.className = 'dbb-kv';
            var sl = document.createElement('strong');
            sl.textContent = 'URL: ';
            u.appendChild(sl);
            var a = document.createElement('a');
            a.href = dbbSafeUrl(moment.url);
            a.textContent = moment.url;
            a.target = '_blank';
            a.rel = 'noopener noreferrer';
            u.appendChild(a);
            body.appendChild(u);
        }
        return body;
    }

    function dbbToggleExpand(rowId) {
        state.expanded[rowId] = !state.expanded[rowId];
        // Re-render the whole relevant column to keep state/DOM in sync.
        if (rowId.indexOf('item-') === 0) dbbRenderItems();
        else dbbRenderMoments();
    }

    window.dbbRemoveItem = function (idx) {
        state.items.splice(idx, 1);
        // Expanded state keyed by index is now stale; reset it.
        state.expanded = {};
        dbbRenderItems();
        dbbUpdateReviewCounts();
        dbbUpdateAccumCount();
    };

    window.dbbRemoveMoment = function (idx) {
        state.moments.splice(idx, 1);
        state.expanded = {};
        dbbRenderMoments();
        dbbUpdateReviewCounts();
        dbbUpdateAccumCount();
    };

    // --- Step 3: preview + save --------------------------------------------

    window.dbbGeneratePreview = function () {
        if (state.items.length === 0 && state.moments.length === 0) {
            showToast('Nothing to preview -- add items or moments first.', 'error');
            return;
        }
        var itemsToSend = state.items
            .filter(function (r) { return r && r.include; })
            .map(dbbStripClientFields);
        var momentsToSend = state.moments
            .filter(function (r) { return r && r.include; })
            .map(dbbStripClientFields);
        if (itemsToSend.length === 0 && momentsToSend.length === 0) {
            showToast('Nothing selected -- check at least one row to include.', 'error');
            return;
        }
        dbbFetchJson('/api/db_builder/consolidate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                items: itemsToSend,
                moments: momentsToSend,
            }),
        }).then(function (data) {
            if (!data) return;
            state.candidateMd = data.candidate_db_md || '';
            state.coverLetterMd = data.cover_letter_db_md || '';
            var wrap = document.getElementById('dbb-preview-wrap');
            var c = document.getElementById('dbb-preview-candidate');
            var cl = document.getElementById('dbb-preview-cl');
            if (c) c.textContent = state.candidateMd || '(empty)';
            if (cl) cl.textContent = state.coverLetterMd || '(empty)';
            if (wrap) wrap.hidden = false;
            showToast('Preview ready.', 'success');
        });
    };

    window.dbbSave = function () {
        if (!state.candidateMd && !state.coverLetterMd) {
            showToast('Generate a preview before saving.', 'error');
            return;
        }
        var modeInput = document.querySelector('input[name="dbb-save-mode"]:checked');
        var mode = modeInput ? modeInput.value : 'replace';
        dbbFetchJson('/api/db_builder/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                candidate_db_md: state.candidateMd,
                cover_letter_db_md: state.coverLetterMd,
                mode: mode,
            }),
        }).then(function (data) {
            if (!data) return;
            var saved = data.saved_bytes || {};
            var parts = [];
            Object.keys(saved).forEach(function (k) {
                parts.push(k + ' (' + saved[k] + ' bytes)');
            });
            var tail = parts.length ? ': ' + parts.join(', ') : '';
            showToast('Saved (' + (data.mode || mode) + ')' + tail, 'success');
        });
    };

    // --- Topic-flag helpers & bulk actions ---------------------------------

    // Normalize an item/moment coming off the API so state carries:
    //   on_topic (defaults to true if missing/undefined),
    //   topic_reason (defaults to ''),
    //   include    (defaults to true unless on_topic === false).
    function dbbNormalizeRow(row) {
        if (!row || typeof row !== 'object') return row;
        var out = {};
        for (var k in row) {
            if (Object.prototype.hasOwnProperty.call(row, k)) out[k] = row[k];
        }
        if (out.on_topic !== false) out.on_topic = true;
        if (typeof out.topic_reason !== 'string') out.topic_reason = '';
        out.include = out.on_topic !== false;
        return out;
    }

    // Strip UI-only fields before we send rows to the server.
    function dbbStripClientFields(row) {
        if (!row || typeof row !== 'object') return row;
        var out = {};
        for (var k in row) {
            if (k === 'include') continue;
            if (Object.prototype.hasOwnProperty.call(row, k)) out[k] = row[k];
        }
        return out;
    }

    function dbbBuildFlagBadge() {
        var badge = document.createElement('span');
        badge.className = 'dbb-flag-badge';
        badge.textContent = '⚠ Flagged';
        badge.title = 'Flagged as possibly off-topic for a resume or cover letter.';
        return badge;
    }

    function dbbBuildIncludeToggle(row, kind, idx) {
        var label = document.createElement('label');
        label.className = 'dbb-list-row-include';
        label.onclick = function (e) { e.stopPropagation(); };
        var cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = !!row.include;
        cb.setAttribute('aria-label',
            'Include in save: ' + (row.title || 'untitled'));
        cb.onclick = function (e) { e.stopPropagation(); };
        cb.onchange = function () {
            dbbSetInclude(kind, idx, cb.checked);
        };
        label.appendChild(cb);
        label.appendChild(document.createTextNode('Include in save'));
        return label;
    }

    function dbbSetInclude(kind, idx, value) {
        var list = kind === 'item' ? state.items : state.moments;
        if (!list[idx]) return;
        list[idx].include = !!value;
        dbbUpdateReviewCounts();
    }

    window.dbbSelectAll = function (kind) {
        var list = kind === 'item' ? state.items : state.moments;
        list.forEach(function (r) { if (r) r.include = true; });
        if (kind === 'item') dbbRenderItems();
        else dbbRenderMoments();
        dbbUpdateReviewCounts();
    };

    window.dbbClearFlagged = function (kind) {
        var list = kind === 'item' ? state.items : state.moments;
        list.forEach(function (r) {
            if (r && r.on_topic === false) r.include = false;
        });
        if (kind === 'item') dbbRenderItems();
        else dbbRenderMoments();
        dbbUpdateReviewCounts();
    };

    // --- Helpers ------------------------------------------------------------

    function dbbFetchJson(url, opts) {
        return fetch(url, opts).then(function (r) {
            return r.json().then(function (data) {
                if (!r.ok || (data && data.error)) {
                    var msg = (data && data.error) || ('HTTP ' + r.status);
                    showToast(msg, 'error');
                    throw new Error(msg);
                }
                return data;
            }, function () {
                // JSON parse failed.
                var msg = 'HTTP ' + r.status + ' -- invalid JSON response';
                showToast(msg, 'error');
                throw new Error(msg);
            });
        }, function (err) {
            showToast('Network error: ' + (err && err.message ? err.message : 'unknown'), 'error');
            throw err;
        });
    }

    function dbbFormatDate(year, month) {
        if (!year && !month) return '';
        if (year && month) {
            var mm = String(month).padStart(2, '0');
            return year + '-' + mm;
        }
        return String(year || month || '');
    }

    function dbbSafeUrl(url) {
        var t = String(url || '').trim();
        if (/^\s*(javascript|data|vbscript|file):/i.test(t)) return '#';
        return t;
    }
})();
