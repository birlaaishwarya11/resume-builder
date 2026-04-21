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

function deleteAccount() {
    var password = prompt('Enter your password to confirm account deletion:');
    if (!password) return;
    fetch('/api/delete_profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: password })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status === 'ok') {
            window.location.href = '/login';
        } else {
            showToast(data.error || 'Failed', 'error');
        }
    });
}
