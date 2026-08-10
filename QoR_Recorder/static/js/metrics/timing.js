(function (global) {
    'use strict';

    const TimingMetric = {
        name: 'metrics.timing',
        category: 'timing',
        schema: {
            setup: { wns: 'number', tns: 'number', nvp: 'number' },
            hold: { wns: 'number', tns: 'number', nvp: 'number' }
        },

        init() {
            global.QoRApp.register(this.name, this);
        },

        getDefault() {
            return { setup: { wns: 0, tns: 0, nvp: 0 }, hold: { wns: 0, tns: 0, nvp: 0 } };
        },

        extract(record) {
            return (record && record.timing) ? record.timing : this.getDefault();
        },

        getWorstWns(timing) {
            if (!timing) return 0;
            const values = [];
            if (timing.setup && typeof timing.setup.wns === 'number') values.push(timing.setup.wns);
            if (timing.hold && typeof timing.hold.wns === 'number') values.push(timing.hold.wns);
            return values.length ? Math.min(...values) : 0;
        },

        getTotalTns(timing) {
            if (!timing) return 0;
            let total = 0;
            if (timing.setup && typeof timing.setup.tns === 'number') total += timing.setup.tns;
            if (timing.hold && typeof timing.hold.tns === 'number') total += timing.hold.tns;
            return total;
        },

        getTotalNvp(timing) {
            if (!timing) return 0;
            let total = 0;
            if (timing.setup && typeof timing.setup.nvp === 'number') total += timing.setup.nvp;
            if (timing.hold && typeof timing.hold.nvp === 'number') total += timing.hold.nvp;
            return total;
        }
    };

    if (global.QoRApp) {
        TimingMetric.init();
    } else {
        document.addEventListener('qorapp:ready', () => TimingMetric.init());
    }

    global.QoRTimingMetric = TimingMetric;
})(window);
