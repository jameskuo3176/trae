(function (global) {
    'use strict';

    const AreaMetric = {
        name: 'metrics.area',
        category: 'area',
        schema: {
            total: 'number',
            combinational: 'number',
            sequential: 'number',
            memory: 'number',
            macro: 'number',
            black_box: 'number'
        },

        init() {
            global.QoRApp.register(this.name, this);
        },

        getDefault() {
            return { total: 0, combinational: 0, sequential: 0, memory: 0, macro: 0, black_box: 0 };
        },

        extract(record) {
            return (record && record.area) ? record.area : this.getDefault();
        },

        getTotal(area) {
            return area && typeof area.total === 'number' ? area.total : 0;
        },

        getStandardCellArea(area) {
            if (!area) return 0;
            return (area.combinational || 0) + (area.sequential || 0);
        }
    };

    if (global.QoRApp) {
        AreaMetric.init();
    } else {
        document.addEventListener('qorapp:ready', () => AreaMetric.init());
    }

    global.QoRAreaMetric = AreaMetric;
})(window);
