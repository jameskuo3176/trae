(function (global) {
    'use strict';

    const ClocksMetric = {
        name: 'metrics.clocks',
        category: 'clocks',
        schema: {
            '<clock_name>': {
                period: 'number',
                wns: 'number',
                tns: 'number',
                nvp: 'number',
                path: 'string'
            }
        },

        init() {
            global.QoRApp.register(this.name, this);
        },

        getDefault() {
            return {};
        },

        extract(record) {
            return (record && record.clocks) ? record.clocks : {};
        },

        getClockNames(clocks) {
            return clocks ? Object.keys(clocks) : [];
        },

        getClock(clocks, name) {
            return clocks && clocks[name] ? clocks[name] : null;
        },

        getWorstClock(clocks) {
            if (!clocks) return null;
            const names = Object.keys(clocks);
            if (!names.length) return null;
            let worst = null;
            names.forEach(n => {
                const c = clocks[n];
                if (!worst || (c.wns !== undefined && c.wns < worst.wns)) {
                    worst = { name: n, ...c };
                }
            });
            return worst;
        }
    };

    if (global.QoRApp) {
        ClocksMetric.init();
    } else {
        document.addEventListener('qorapp:ready', () => ClocksMetric.init());
    }

    global.QoRClocksMetric = ClocksMetric;
})(window);
