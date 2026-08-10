(function (global) {
    'use strict';

    const DcReport = {
        name: 'ui.dc-report',

        init() {
            global.QoRApp.register(this.name, this);
        },

        render(container, record) {
            if (!container || !record) return;
            const metrics = global.QoRApp.getModule('metrics.timing');
            const timing = metrics ? metrics.extract(record) : null;
            container.innerHTML = `<pre class="dc-report-raw">${JSON.stringify(record, null, 2)}</pre>`;
        },

        clear(container) {
            if (container) container.innerHTML = '';
        },

        formatMetric(value, unit) {
            if (value === null || value === undefined) return '-';
            if (typeof value === 'number') {
                return value.toFixed(3) + (unit ? ` ${unit}` : '');
            }
            return String(value);
        }
    };

    if (global.QoRApp) {
        DcReport.init();
    } else {
        document.addEventListener('qorapp:ready', () => DcReport.init());
    }

    global.QoRDcReport = DcReport;
})(window);
