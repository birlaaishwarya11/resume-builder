/**
 * Resume editor: Ace setup, save, preview, PDF download, keyboard shortcuts, history panel.
 */
(function() {
    'use strict';

    // --- Ace editor setup ---
    var editor = ace.edit('ace-editor');
    editor.setTheme('ace/theme/chrome');
    editor.session.setMode('ace/mode/yaml');
    editor.setOptions({
        fontSize: '13px',
        showPrintMargin: false,
        wrap: true,
        tabSize: 2,
        useSoftTabs: true
    });

    // Expose editor globally for other modules
    window.resumeEditor = editor;

    // --- Preview ---
    var previewTimer = null;

    function updatePreview() {
        var content = editor.getValue();
        fetch('/api/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ yaml_content: content })
        })
        .then(function(r) { return r.text(); })
        .then(function(html) {
            var iframe = document.getElementById('preview-iframe');
            if (iframe) iframe.srcdoc = html;
        })
        .catch(function(err) {
            console.error('Preview failed:', err);
        });
    }

    // Debounced auto-preview on editor changes
    editor.session.on('change', function() {
        clearTimeout(previewTimer);
        previewTimer = setTimeout(updatePreview, 600);
    });

    // Initial preview
    setTimeout(updatePreview, 200);

    // Expose for other modules
    window.updatePreview = updatePreview;

    // --- Save ---
    function save() {
        var content = editor.getValue();
        fetch('/api/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ yaml_content: content })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) {
                showToast(data.error, 'error');
                return;
            }
            showToast('Saved', 'success');
        })
        .catch(function(err) {
            showToast('Save failed: ' + err, 'error');
        });
    }

    document.getElementById('btn-save').addEventListener('click', save);

    // --- Keyboard shortcuts ---
    editor.commands.addCommand({
        name: 'save',
        bindKey: { win: 'Ctrl-S', mac: 'Cmd-S' },
        exec: function() { save(); }
    });

    // Global Ctrl+S fallback
    document.addEventListener('keydown', function(e) {
        if ((e.ctrlKey || e.metaKey) && e.key === 's') {
            e.preventDefault();
            save();
        }
    });

    // --- Download PDF ---
    document.getElementById('btn-download-pdf').addEventListener('click', function() {
        var content = editor.getValue();
        var form = document.createElement('form');
        form.method = 'POST';
        form.action = '/api/download_pdf';
        var input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'yaml_content';
        input.value = content;
        form.appendChild(input);
        document.body.appendChild(form);
        form.submit();
        form.remove();
    });

    // --- Style selector ---
    var styleSelect = document.getElementById('style-select');
    if (styleSelect) {
        styleSelect.addEventListener('change', function() {
            fetch('/api/set_style', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ style: styleSelect.value })
            })
            .then(function() { updatePreview(); })
            .catch(function(err) { showToast('Style change failed: ' + err, 'error'); });
        });
    }

    // --- History panel ---
    var historyPanel = document.getElementById('history-panel');
    var historyClose = document.getElementById('history-panel-close');
    var btnHistory = document.getElementById('btn-history');
    var overlay = document.getElementById('panel-overlay');

    function closeAllPanels() {
        document.querySelectorAll('.side-panel').forEach(function(p) {
            p.classList.remove('open');
        });
        overlay.classList.remove('visible');
    }

    function toggleHistory() {
        var isOpen = historyPanel.classList.contains('open');
        closeAllPanels();
        if (!isOpen) {
            historyPanel.classList.add('open');
            overlay.classList.add('visible');
            loadHistory();
        }
    }

    btnHistory.addEventListener('click', toggleHistory);
    historyClose.addEventListener('click', closeAllPanels);
    overlay.addEventListener('click', closeAllPanels);

    function loadHistory() {
        var listEl = document.getElementById('history-list');
        listEl.innerHTML = '<div class="panel-loading">Loading history...</div>';

        fetch('/api/versions')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.versions || data.versions.length === 0) {
                listEl.innerHTML = '<p class="text-sm text-muted">No saved versions yet.</p>';
                return;
            }
            listEl.innerHTML = '';
            data.versions.forEach(function(v) {
                var item = document.createElement('div');
                item.className = 'history-item';
                var meta = '<div class="history-meta">' +
                    '<span class="history-label">' + (v.label || 'Version ' + v.id) + '</span>' +
                    '<span class="history-date">' + (v.created_at || '') + '</span>' +
                    '</div>';
                var tags = '';
                if (v.tags && v.tags.length) {
                    tags = '<div class="history-tags">';
                    v.tags.forEach(function(t) {
                        tags += '<span class="history-tag">' + t + '</span>';
                    });
                    tags += '</div>';
                }
                item.innerHTML = meta + tags;
                item.addEventListener('click', function() {
                    loadVersion(v.id);
                });
                listEl.appendChild(item);
            });
        })
        .catch(function(err) {
            listEl.innerHTML = '<p class="text-sm" style="color:#c62828;">Failed to load history: ' + err + '</p>';
        });
    }

    function loadVersion(versionId) {
        fetch('/api/versions/' + versionId)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) { showToast(data.error, 'error'); return; }
            editor.setValue(data.yaml_content || '', -1);
            updatePreview();
            closeAllPanels();
            showToast('Loaded version: ' + (data.label || versionId), 'info');
        })
        .catch(function(err) {
            showToast('Failed to load version: ' + err, 'error');
        });
    }

    // Expose for jd.js
    window.closeAllPanels = closeAllPanels;
})();
