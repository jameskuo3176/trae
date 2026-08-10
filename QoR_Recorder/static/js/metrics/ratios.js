(function (global) {
    'use strict';

    const RatiosMetric = {
        name: 'metrics.ratios',
        category: 'ratios',
        schema: {
            mbb_ratio: 'number',
            clock_gating_ratio: 'number',
            utilization: 'number'
        },

        init() {
            global.QoRApp.register(this.name, this);
        },

        getDefault() {
            return { mbb_ratio: 0, clock_gating_ratio: 0, utilization: 0 };
        },

        extract(record) {
            return (record && record.ratios) ? record.ratios : this.getDefault();
        },

        getUtilization(ratios) {
            return ratios && typeof ratios.utilization === 'number' ? ratios.utilization : 0;
        }
    };

    if (global.QoRApp) {
        RatiosMetric.init();
    } else {
        document.addEventListener('qorapp:ready', () => RatiosMetric.init());
    }

    global.QoRRatiosMetric = RatiosMetric;
})(window);
