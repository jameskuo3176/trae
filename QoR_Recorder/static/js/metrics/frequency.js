(function (global) {
    'use strict';

    const FrequencyMetric = {
        name: 'metrics.frequency',
        category: 'frequency',
        schema: {
            target: 'number',
            achieved: 'number'
        },

        init() {
            global.QoRApp.register(this.name, this);
        },

        getDefault() {
            return { target: 0, achieved: 0 };
        },

        extract(record) {
            return (record && record.frequency) ? record.frequency : this.getDefault();
        },

        getAchieved(freq) {
            return freq && typeof freq.achieved === 'number' ? freq.achieved : 0;
        },

        getTarget(freq) {
            return freq && typeof freq.target === 'number' ? freq.target : 0;
        }
    };

    if (global.QoRApp) {
        FrequencyMetric.init();
    } else {
        document.addEventListener('qorapp:ready', () => FrequencyMetric.init());
    }

    global.QoRFrequencyMetric = FrequencyMetric;
})(window);
