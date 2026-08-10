(function (global) {
    'use strict';

    const ViolationPanel = {
        name: 'ui.violation-panel',

        init() {
            global.QoRApp.register(this.name, this);
        },

        render(container, violations) {
            if (!container) return;
            if (!violations || !violations.length) {
                container.innerHTML = '<div class="violation-empty">No violations</div>';
                return;
            }
            const rows = violations.map(v => `
                <tr>
                    <td>${v.timing_group || '-'}</td>
                    <td>${v.type || '-'}</td>
                    <td class="${v.slack < 0 ? 'negative' : ''}">${v.slack !== undefined ? v.slack.toFixed(4) : '-'}</td>
                    <td>${v.startpoint || '-'}</td>
                    <td>${v.endpoint || '-'}</td>
                    <td>${v.depth || '-'}</td>
                </tr>
            `).join('');
            container.innerHTML = `
                <table class="violation-table">
                    <thead><tr>
                        <th>Clock Group</th><th>Type</th><th>Slack</th>
                        <th>Startpoint</th><th>Endpoint</th><th>Depth</th>
                    </tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            `;
        },

        clear(container) {
            if (container) container.innerHTML = '';
        },

        filter(violations, criteria) {
            if (!violations) return [];
            return violations.filter(v => {
                if (criteria.type && v.type !== criteria.type) return false;
                if (criteria.timing_group && v.timing_group !== criteria.timing_group) return false;
                if (criteria.minSlack !== undefined && v.slack < criteria.minSlack) return false;
                return true;
            });
        }
    };

    if (global.QoRApp) {
        ViolationPanel.init();
    } else {
        document.addEventListener('qorapp:ready', () => ViolationPanel.init());
    }

    global.QoRViolationPanel = ViolationPanel;
})(window);
