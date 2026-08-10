(function (global) {
    'use strict';

    const PowerMetric = {
        name: 'metrics.power',
        category: 'power',
        schema: {
            internal: 'number',
            switching: 'number',
            leakage: 'number',
            total: 'number'
        },

        init() {
            global.QoRApp.register(this.name, this);
        },

        getDefault() {
            return { internal: 0, switching: 0, leakage: 0, total: 0 };
        },

        extract(record) {
            return (record && record.power) ? record.power : this.getDefault();
        },

        getTotal(power) {
            return power && typeof power.total === 'number' ? power.total : 0;
        }
    };

    if (global.QoRApp) {
        PowerMetric.init();
    } else {
        document.addEventListener('qorapp:ready', () => PowerMetric.init());
    }

    global.QoRPowerMetric = PowerMetric;
})(window);
