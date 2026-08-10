(function (global) {
    'use strict';

    const CongestionMetric = {
        name: 'metrics.congestion',
        category: 'congestion',
        schema: {
            h: 'number',
            v: 'number',
            b: 'number',
            max: 'number'
        },

        init() {
            global.QoRApp.register(this.name, this);
        },

        getDefault() {
            return { h: 0, v: 0, b: 0, max: 0 };
        },

        extract(record) {
            return (record && record.congestion) ? record.congestion : this.getDefault();
        },

        getMax(congestion) {
            if (!congestion) return 0;
            if (typeof congestion.max === 'number') return congestion.max;
            return Math.max(congestion.h || 0, congestion.v || 0, congestion.b || 0);
        }
    };

    if (global.QoRApp) {
        CongestionMetric.init();
    } else {
        document.addEventListener('qorapp:ready', () => CongestionMetric.init());
    }

    global.QoRCongestionMetric = CongestionMetric;
})(window);
