/**
 * JD Match panel: toggle, tabs, analyze, generate, find, display results.
 * Depends on: editor.js (window.resumeEditor, window.closeAllPanels, window.updatePreview)
 *             tags.js (renderTagChips)
 */
(function() {
    'use strict';

    var jdPanel = document.getElementById('jd-panel');
    var jdClose = document.getElementById('jd-panel-close');
    var btnJdMatch = document.getElementById('btn-jd-match');
    var overlay = document.getElementById('panel-overlay');
    var resultsEl = document.getElementById('jd-results');

    // Current tags state
    var currentTags = [];

    // --- Panel toggle ---
    function toggleJdPanel() {
        var isOpen = jdPanel.classList.contains('open');
        window.closeAllPanels();
        if (!isOpen) {
            jdPanel.classList.add('open');
            overlay.classList.add('visible');
        }
    }

    btnJdMatch.addEventListener('click', toggleJdPanel);
    jdClose.addEventListener('click', window.closeAllPanels);

    // --- Tab switching ---
    var tabs = document.querySelectorAll('.panel-tab');
    tabs.forEach(function(tab) {
        tab.addEventListener('click', function() {
            tabs.forEach(function(t) { t.classList.remove('active'); });
            tab.classList.add('active');
            document.querySelectorAll('.tab-content').forEach(function(tc) {
                tc.classList.remove('active');
            });
            var target = document.getElementById('tab-' + tab.getAttribute('data-tab'));
            if (target) target.classList.add('active');
        });
    });

    // --- Analyze JD ---
    document.getElementById('btn-analyze-jd').addEventListener('click', function() {
        var jdText = document.getElementById('jd-text').value.trim();
        if (!jdText) { showToast('Please paste a job description first.', 'error'); return; }

        var btn = this;
        btn.disabled = true;
        btn.textContent = 'Analyzing...';

        fetch('/api/jd_analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                jd_text: jdText,
                yaml_content: window.resumeEditor.getValue()
            })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) { showToast(data.error, 'error'); return; }
            displayResults(data);
        })
        .catch(function(err) { showToast('Analysis failed: ' + err, 'error'); })
        .finally(function() { btn.disabled = false; btn.textContent = 'Analyze'; });
    });

    // --- Generate Resume from JD ---
    document.getElementById('btn-generate-resume').addEventListener('click', function() {
        var jdText = document.getElementById('jd-text').value.trim();
        if (!jdText) { showToast('Please paste a job description first.', 'error'); return; }

        var btn = this;
        btn.disabled = true;
        btn.textContent = 'Generating...';

        fetch('/api/jd_generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ jd_text: jdText })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) { showToast(data.error, 'error'); return; }
            if (data.yaml_content) {
                window.resumeEditor.setValue(data.yaml_content, -1);
                window.updatePreview();
            }
            displayResults(data);
            showToast('Resume generated from JD', 'success');
        })
        .catch(function(err) { showToast('Generation failed: ' + err, 'error'); })
        .finally(function() { btn.disabled = false; btn.textContent = 'Generate Resume'; });
    });

    // --- Find JD by company + role ---
    document.getElementById('btn-find-jd').addEventListener('click', function() {
        var company = document.getElementById('jd-company').value.trim();
        var role = document.getElementById('jd-role').value.trim();
        if (!company || !role) { showToast('Enter both company and role.', 'error'); return; }

        var btn = this;
        btn.disabled = true;
        btn.textContent = 'Searching...';

        fetch('/api/jd_find', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ company: company, role: role })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) { showToast(data.error, 'error'); return; }
            if (data.jd_text) {
                document.getElementById('jd-text').value = data.jd_text;
                // Switch to Paste JD tab
                tabs.forEach(function(t) { t.classList.remove('active'); });
                document.querySelector('[data-tab="paste-jd"]').classList.add('active');
                document.querySelectorAll('.tab-content').forEach(function(tc) { tc.classList.remove('active'); });
                document.getElementById('tab-paste-jd').classList.add('active');
                showToast('Found JD for ' + company + ' ' + role, 'success');
            }
            if (data.ats_score) displayResults(data);
        })
        .catch(function(err) { showToast('Search failed: ' + err, 'error'); })
        .finally(function() { btn.disabled = false; btn.textContent = 'Find JD'; });
    });

    // --- Fetch JD from URL ---
    document.getElementById('btn-fetch-url').addEventListener('click', function() {
        var url = document.getElementById('jd-url').value.trim();
        if (!url) { showToast('Enter a job posting URL.', 'error'); return; }

        var btn = this;
        btn.disabled = true;
        btn.textContent = 'Fetching...';

        fetch('/api/jd_find', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) { showToast(data.error, 'error'); return; }
            if (data.jd_text) {
                document.getElementById('jd-text').value = data.jd_text;
                tabs.forEach(function(t) { t.classList.remove('active'); });
                document.querySelector('[data-tab="paste-jd"]').classList.add('active');
                document.querySelectorAll('.tab-content').forEach(function(tc) { tc.classList.remove('active'); });
                document.getElementById('tab-paste-jd').classList.add('active');
                showToast('JD fetched from URL', 'success');
            }
        })
        .catch(function(err) { showToast('Fetch failed: ' + err, 'error'); })
        .finally(function() { btn.disabled = false; btn.textContent = 'Fetch & Analyze'; });
    });

    // --- Display results ---
    function displayResults(data) {
        resultsEl.style.display = 'block';

        // ATS score badge
        var badge = document.getElementById('ats-score-badge');
        var score = data.ats_score || 0;
        badge.textContent = score + '/100';
        badge.className = 'score-badge';
        if (score >= 90) badge.classList.add('score-high');
        else if (score >= 70) badge.classList.add('score-mid');
        else badge.classList.add('score-low');

        // Tags
        currentTags = data.tags || [];
        var chipContainer = document.getElementById('jd-tag-chips');
        renderTagChips(chipContainer, currentTags, {
            editable: true,
            onRemove: function(tag) {
                currentTags = currentTags.filter(function(t) { return t !== tag; });
                renderTagChips(chipContainer, currentTags, this);
                syncTags();
            },
            onAdd: function(tag) {
                if (currentTags.indexOf(tag) === -1) {
                    currentTags.push(tag);
                    renderTagChips(chipContainer, currentTags, this);
                    syncTags();
                }
            }
        });

        // Assessment
        var assessmentEl = document.getElementById('jd-assessment');
        assessmentEl.textContent = data.assessment || '';
    }

    function syncTags() {
        fetch('/api/tags', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tags: currentTags })
        }).catch(function() {});
    }
})();
