/**
 * Database editor -- shared logic for all 4 database editor pages.
 * Uses Ace.js in markdown mode with live preview.
 */

var _editor = null;
var _dbType = null;
var _saveTimeout = null;

function initDatabaseEditor(dbType) {
    _dbType = dbType;

    // Initialize Ace editor
    _editor = ace.edit('editor');
    _editor.setTheme('ace/theme/chrome');
    _editor.session.setMode('ace/mode/markdown');
    _editor.setOptions({
        fontSize: '14px',
        wrap: true,
        showPrintMargin: false,
        tabSize: 2,
    });

    // Load content
    fetch('/api/databases/' + dbType)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            _editor.setValue(data.content || '', -1);
            updatePreview();
        });

    // Live preview on change (debounced)
    _editor.on('change', function() {
        clearTimeout(_saveTimeout);
        _saveTimeout = setTimeout(updatePreview, 500);
    });

    // Keyboard shortcut: Ctrl/Cmd+S to save
    _editor.commands.addCommand({
        name: 'save',
        bindKey: { win: 'Ctrl-S', mac: 'Cmd-S' },
        exec: function() { saveContent(); }
    });
}

function updatePreview() {
    var content = _editor.getValue();
    var preview = document.getElementById('preview');
    // Simple markdown to HTML (basic, no external library needed)
    preview.innerHTML = simpleMarkdownToHtml(content);
}

function saveContent() {
    var content = _editor.getValue();
    var status = document.getElementById('save-status');
    status.textContent = 'Saving...';

    fetch('/api/databases/' + _dbType, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: content })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status === 'ok') {
            status.textContent = 'Saved';
            setTimeout(function() { status.textContent = ''; }, 2000);
            showToast('Saved', 'success');
        } else {
            status.textContent = 'Error';
            showToast(data.error || 'Save failed', 'error');
        }
    })
    .catch(function() {
        status.textContent = 'Error';
        showToast('Save failed', 'error');
    });
}

/**
 * Basic markdown to HTML converter.
 * Handles: headers, bold, italic, code, lists, links, hr, tables, paragraphs.
 */
function simpleMarkdownToHtml(md) {
    if (!md) return '';
    var lines = md.split('\n');
    var html = [];
    var inList = false;
    var inCode = false;
    var inTable = false;

    for (var i = 0; i < lines.length; i++) {
        var line = lines[i];

        // Code blocks
        if (line.trim().startsWith('```')) {
            if (inCode) {
                html.push('</code></pre>');
                inCode = false;
            } else {
                inCode = true;
                html.push('<pre><code>');
            }
            continue;
        }
        if (inCode) {
            html.push(escapeHtml(line));
            html.push('\n');
            continue;
        }

        // Table detection
        if (line.trim().match(/^\|.*\|$/)) {
            if (!inTable) {
                inTable = true;
                html.push('<table>');
            }
            if (line.trim().match(/^\|[\s\-:|]+\|$/)) continue; // separator row
            var cells = line.trim().split('|').filter(function(c) { return c.trim(); });
            html.push('<tr>');
            cells.forEach(function(c) {
                html.push('<td>' + inlineMarkdown(c.trim()) + '</td>');
            });
            html.push('</tr>');
            continue;
        } else if (inTable) {
            inTable = false;
            html.push('</table>');
        }

        // Headers
        var hMatch = line.match(/^(#{1,6})\s+(.+)/);
        if (hMatch) {
            if (inList) { html.push('</ul>'); inList = false; }
            var level = hMatch[1].length;
            html.push('<h' + level + '>' + inlineMarkdown(hMatch[2]) + '</h' + level + '>');
            continue;
        }

        // Horizontal rule
        if (line.trim().match(/^(-{3,}|\*{3,}|_{3,})$/)) {
            if (inList) { html.push('</ul>'); inList = false; }
            html.push('<hr>');
            continue;
        }

        // List items
        if (line.match(/^\s*[-*+]\s+/)) {
            if (!inList) { html.push('<ul>'); inList = true; }
            html.push('<li>' + inlineMarkdown(line.replace(/^\s*[-*+]\s+/, '')) + '</li>');
            continue;
        }

        // Numbered lists
        if (line.match(/^\s*\d+\.\s+/)) {
            if (!inList) { html.push('<ul>'); inList = true; }
            html.push('<li>' + inlineMarkdown(line.replace(/^\s*\d+\.\s+/, '')) + '</li>');
            continue;
        }

        if (inList) { html.push('</ul>'); inList = false; }

        // Empty lines
        if (!line.trim()) {
            continue;
        }

        // Paragraphs
        html.push('<p>' + inlineMarkdown(line) + '</p>');
    }

    if (inList) html.push('</ul>');
    if (inCode) html.push('</code></pre>');
    if (inTable) html.push('</table>');

    return html.join('\n');
}

function inlineMarkdown(text) {
    text = escapeHtml(text);
    text = text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/\*(.+?)\*/g, '<em>$1</em>');
    text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
    text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function(_m, label, url) {
        return '<a href="' + safeUrl(url) + '" rel="noopener noreferrer">' + label + '</a>';
    });
    return text;
}

function safeUrl(url) {
    // Block javascript:, data:, vbscript:, file: schemes that escapeHtml does
    // NOT neutralise. Allow only http(s)/mailto/relative URLs in the preview.
    var trimmed = String(url || '').trim();
    if (/^\s*(javascript|data|vbscript|file):/i.test(trimmed)) {
        return '#';
    }
    return trimmed;
}

function escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
