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
    var PAGE_HEIGHT_PX = 11 * 96; // Letter page height at 96 DPI

    function resizePreview(iframe) {
        var doc = iframe.contentDocument;
        if (!doc || !doc.body) return;

        // Clear anything we set on a previous run before measuring, otherwise
        // min-height / iframe height keep the document padded out and the page
        // count never shrinks when the resume gets shorter.
        doc.documentElement.style.minHeight = '';
        iframe.style.height = '';
        doc.querySelectorAll('.__preview_page_break__').forEach(function(el) { el.remove(); });

        var contentHeight = Math.max(doc.body.scrollHeight, doc.documentElement.scrollHeight);
        var pages = Math.max(1, Math.ceil(contentHeight / PAGE_HEIGHT_PX));
        var iframeHeightPx = pages * PAGE_HEIGHT_PX;
        iframe.style.height = iframeHeightPx + 'px';

        // Draw page-break markers inside the iframe
        doc.documentElement.style.position = 'relative';
        doc.documentElement.style.minHeight = iframeHeightPx + 'px';
        for (var i = 1; i < pages; i++) {
            var marker = doc.createElement('div');
            marker.className = '__preview_page_break__';
            marker.style.cssText =
                'position:absolute;left:0;right:0;top:' + (i * PAGE_HEIGHT_PX) + 'px;' +
                'border-top:2px dashed rgba(255,0,0,0.4);height:0;pointer-events:none;z-index:9999;';
            var label = doc.createElement('div');
            label.textContent = 'Page ' + (i + 1);
            label.style.cssText =
                'position:absolute;top:4px;right:8px;font:9pt sans-serif;color:#c62828;' +
                'background:rgba(255,255,255,0.9);padding:1px 6px;border-radius:3px;';
            marker.appendChild(label);
            doc.documentElement.appendChild(marker);
        }

        var badge = document.getElementById('page-count-badge');
        if (badge) {
            badge.textContent = pages + (pages === 1 ? ' page' : ' pages');
            badge.style.color = pages > 1 ? '#c62828' : '';
            badge.style.fontWeight = pages > 1 ? '600' : '';
        }
    }

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
            if (!iframe) return;
            // Write directly to iframe document (like SimpleLocalBuilder)
            var doc = iframe.contentDocument;
            doc.open();
            doc.write(html);
            doc.close();
            // Resize after content has rendered
            setTimeout(function() { resizePreview(iframe); }, 50);
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

    // Initial preview is server-rendered into srcdoc; just size it once
    // the browser finishes parsing the inlined document.
    var initialIframe = document.getElementById('preview-iframe');
    if (initialIframe) {
        if (initialIframe.contentDocument && initialIframe.contentDocument.readyState === 'complete') {
            resizePreview(initialIframe);
        } else {
            initialIframe.addEventListener('load', function onFirstLoad() {
                initialIframe.removeEventListener('load', onFirstLoad);
                resizePreview(initialIframe);
            });
        }
    }

    // Expose for other modules
    window.updatePreview = updatePreview;

    // --- Save ---
    function getLabel() {
        var el = document.getElementById('label-input');
        return el ? el.value.trim() : '';
    }

    function save() {
        var content = editor.getValue();
        var keyword = getLabel();
        var labelForMsg = keyword || 'default';
        fetch('/api/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ yaml_content: content, keyword: labelForMsg })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.status === 'error' || data.error) {
                showToast(data.message || data.error, 'error');
                return;
            }
            showToast('Saved version "' + labelForMsg + '"', 'success');
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
        var keyword = getLabel();
        var form = document.createElement('form');
        form.method = 'POST';
        form.action = '/api/download_pdf';
        var yamlInput = document.createElement('input');
        yamlInput.type = 'hidden';
        yamlInput.name = 'yaml_content';
        yamlInput.value = content;
        form.appendChild(yamlInput);
        if (keyword) {
            var kwInput = document.createElement('input');
            kwInput.type = 'hidden';
            kwInput.name = 'keyword';
            kwInput.value = keyword;
            form.appendChild(kwInput);
        }
        document.body.appendChild(form);
        form.submit();
        form.remove();
    });

    // --- Preview PDF (popup modal) ---
    var previewModal = document.getElementById('preview-modal');
    var previewFrame = document.getElementById('preview-modal-frame');
    var previewModalClose = document.getElementById('preview-modal-close');

    document.getElementById('btn-preview-pdf').addEventListener('click', function() {
        var content = editor.getValue();
        var keyword = getLabel();

        fetch('/api/download_pdf', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ yaml_content: content, keyword: keyword, inline: true })
        })
        .then(function(response) {
            if (!response.ok) throw new Error('Failed to generate PDF');
            return response.blob();
        })
        .then(function(blob) {
            var url = window.URL.createObjectURL(blob);
            previewFrame.src = url;
            previewModal.style.display = 'flex';
        })
        .catch(function(err) {
            showToast('Preview failed: ' + err.message, 'error');
        });
    });

    if (previewModalClose) {
        previewModalClose.addEventListener('click', function() {
            previewModal.style.display = 'none';
            previewFrame.src = '';
        });
    }
    // Close on backdrop click
    if (previewModal) {
        previewModal.addEventListener('click', function(e) {
            if (e.target === previewModal) {
                previewModal.style.display = 'none';
                previewFrame.src = '';
            }
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
            var versions = Array.isArray(data) ? data : (data.versions || []);
            if (versions.length === 0) {
                listEl.innerHTML = '<p class="text-sm text-muted">No saved versions yet.</p>';
                return;
            }
            listEl.innerHTML = '';
            versions.forEach(function(v) {
                var item = document.createElement('div');
                item.className = 'history-item';
                var displayLabel = v.label || 'Version ' + v.id;
                var html =
                    '<div style="display:flex; justify-content:space-between; align-items:center;">' +
                        '<strong style="font-size:0.88em;">' + displayLabel + '</strong>' +
                        '<div>' +
                            '<button class="btn btn-primary btn-sm" style="padding:2px 8px; font-size:0.72em;" data-action="restore" data-id="' + v.id + '" data-label="' + displayLabel.replace(/"/g, '&quot;') + '">Restore</button>' +
                            '<button class="btn btn-danger btn-sm" style="padding:2px 8px; font-size:0.72em; margin-left:4px;" data-action="delete" data-id="' + v.id + '" data-label="' + displayLabel.replace(/"/g, '&quot;') + '">Delete</button>' +
                        '</div>' +
                    '</div>' +
                    '<div style="font-size:0.75em; color:#888; margin-top:2px;">' + (v.created_at || '') + '</div>';
                if (v.source) {
                    html += '<div style="font-size:0.7em; color:#aaa; margin-top:1px;">Source: ' + v.source + '</div>';
                }
                if (v.tags && v.tags.length) {
                    html += '<div class="history-tags">';
                    v.tags.forEach(function(t) {
                        html += '<span class="history-tag">' + t + '</span>';
                    });
                    html += '</div>';
                }
                item.innerHTML = html;
                listEl.appendChild(item);
            });

            // Delegate click events for restore/delete buttons
            listEl.onclick = function(e) {
                var btn = e.target.closest('[data-action]');
                if (!btn) return;
                e.stopPropagation();
                var action = btn.dataset.action;
                var id = parseInt(btn.dataset.id, 10);
                var label = btn.dataset.label;
                if (action === 'restore') restoreVersion(id, label);
                else if (action === 'delete') deleteVersion(id, label);
            };
        })
        .catch(function(err) {
            listEl.innerHTML = '<p class="text-sm" style="color:#c62828;">Failed to load history: ' + err + '</p>';
        });
    }

    function restoreVersion(versionId, label) {
        fetch('/api/versions/restore', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ version_id: versionId })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) { showToast(data.error, 'error'); return; }
            editor.setValue(data.yaml || '', -1);
            updatePreview();
            closeAllPanels();
            showToast('Restored: ' + label, 'success');
        })
        .catch(function(err) {
            showToast('Failed to restore: ' + err, 'error');
        });
    }

    function deleteVersion(versionId, label) {
        if (!confirm('Delete version "' + label + '"? This cannot be undone.')) return;
        fetch('/api/versions/' + versionId, { method: 'DELETE' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) { showToast(data.error, 'error'); return; }
            showToast('Version deleted.', 'info');
            loadHistory();
        })
        .catch(function(err) {
            showToast('Failed to delete: ' + err, 'error');
        });
    }

    // Expose for jd.js
    window.closeAllPanels = closeAllPanels;
})();
