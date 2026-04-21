/**
 * Tag chip component.
 *
 * renderTagChips(container, tags, { editable, onRemove, onAdd })
 * - container: DOM element to render into
 * - tags: array of strings
 * - options.editable: show remove buttons and add input
 * - options.onRemove(tag): callback when tag removed
 * - options.onAdd(tag): callback when tag added
 */

var TAG_COLORS = [
    { bg: '#e3f2fd', fg: '#1565c0' },
    { bg: '#f3e5f5', fg: '#7b1fa2' },
    { bg: '#e8f5e9', fg: '#2e7d32' },
    { bg: '#fff3e0', fg: '#e65100' },
    { bg: '#fce4ec', fg: '#c62828' },
    { bg: '#e0f7fa', fg: '#00695c' },
    { bg: '#f1f8e9', fg: '#33691e' },
    { bg: '#fff8e1', fg: '#f57f17' },
];

function tagColor(tag) {
    var hash = 0;
    for (var i = 0; i < tag.length; i++) {
        hash = ((hash << 5) - hash) + tag.charCodeAt(i);
        hash |= 0;
    }
    return TAG_COLORS[Math.abs(hash) % TAG_COLORS.length];
}

function renderTagChips(container, tags, options) {
    options = options || {};
    container.innerHTML = '';
    var wrapper = document.createElement('div');
    wrapper.className = 'tag-chips';

    (tags || []).forEach(function(tag) {
        var color = tagColor(tag);
        var chip = document.createElement('span');
        chip.className = 'tag-chip';
        chip.style.background = color.bg;
        chip.style.color = color.fg;
        chip.textContent = tag;

        if (options.editable && options.onRemove) {
            var rm = document.createElement('span');
            rm.className = 'tag-remove';
            rm.textContent = '\u00d7';
            rm.onclick = function() { options.onRemove(tag); };
            chip.appendChild(rm);
        }
        wrapper.appendChild(chip);
    });

    if (options.editable && options.onAdd) {
        var input = document.createElement('input');
        input.type = 'text';
        input.placeholder = 'Add tag...';
        input.style.cssText = 'width:80px;padding:2px 6px;border:1px solid #ddd;border-radius:12px;font-size:0.75em;';
        input.onkeydown = function(e) {
            if (e.key === 'Enter' && input.value.trim()) {
                options.onAdd(input.value.trim().toLowerCase());
                input.value = '';
            }
        };
        wrapper.appendChild(input);
    }

    container.appendChild(wrapper);
}
