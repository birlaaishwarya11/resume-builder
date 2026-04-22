/* Settings page logic */

function loadAiConfig() {
    fetch('/api/settings/ai_config')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.provider) {
                document.getElementById('ai-provider').value = data.provider;
            }
            if (data.model) {
                document.getElementById('ai-model').value = data.model;
            }
            var status = document.getElementById('ai-key-status');
            if (data.has_key) {
                status.textContent = 'Key saved (encrypted)';
                status.style.color = '#2e7d32';
            } else {
                status.textContent = 'No key configured';
                status.style.color = '#888';
            }
        });
}

function saveAiConfig() {
    var provider = document.getElementById('ai-provider').value;
    var apiKey = document.getElementById('ai-key').value.trim();
    var model = document.getElementById('ai-model').value.trim();

    if (!apiKey) {
        showToast('API key is required', 'error');
        return;
    }

    fetch('/api/settings/ai_config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: provider, api_key: apiKey, model: model })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status === 'ok') {
            showToast('AI configuration saved', 'success');
            document.getElementById('ai-key').value = '';
            loadAiConfig();
        } else {
            showToast(data.error || 'Failed to save', 'error');
        }
    });
}

function deleteAiConfig() {
    if (!confirm('Remove your stored API key?')) return;
    fetch('/api/settings/ai_config', { method: 'DELETE' })
        .then(function(r) { return r.json(); })
        .then(function() {
            showToast('API key removed', 'success');
            loadAiConfig();
        });
}

function saveHeader() {
    var header = {
        name: document.getElementById('header-name').value,
        contact: {
            email: document.getElementById('header-email').value,
            phone: document.getElementById('header-phone').value,
            location: document.getElementById('header-location').value,
            github: document.getElementById('header-github').value,
            linkedin: document.getElementById('header-linkedin').value,
            portfolio_label: 'Portfolio',
            portfolio_url: document.getElementById('header-portfolio').value,
        }
    };
    fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ header: header })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status === 'ok') showToast('Header saved', 'success');
        else showToast(data.error || 'Failed', 'error');
    });
}

function saveSectionNames() {
    var inputs = document.querySelectorAll('.section-name-input');
    var names = {};
    inputs.forEach(function(input) {
        names[input.dataset.key] = input.value;
    });
    fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ section_names: names })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status === 'ok') showToast('Section names saved', 'success');
        else showToast(data.error || 'Failed', 'error');
    });
}

function saveStyle() {
    var style = {
        font_family: document.getElementById('style-font-family').value,
        font_size: document.getElementById('style-font-size').value,
        line_height: document.getElementById('style-line-height').value,
        margin: document.getElementById('style-margin').value,
        accent_color: document.getElementById('style-accent-color').value,
    };
    fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ style: style })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status === 'ok') showToast('Styling saved', 'success');
        else showToast(data.error || 'Failed', 'error');
    });
}

// Sync accent color picker <-> hex input
(function() {
    var picker = document.getElementById('style-accent-color');
    var hex = document.getElementById('style-accent-hex');
    if (picker && hex) {
        picker.addEventListener('input', function() { hex.value = picker.value; });
        hex.addEventListener('input', function() {
            if (/^#[0-9A-Fa-f]{6}$/.test(hex.value.trim())) {
                picker.value = hex.value.trim();
            }
        });
    }
})();

// deleteAccount is handled by the global modal in base.html (showDeleteModal)
