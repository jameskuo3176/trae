(function (global) {
    'use strict';

    const CellsMetric = {
        name: 'metrics.cells',
        category: 'cells',
        schema: {
            cell_count: 'number',
            instance_count: 'number',
            net_count: 'number',
            sequential_cell_count: 'number'
        },

        init() {
            global.QoRApp.register(this.name, this);
        },

        getDefault() {
            return { cell_count: 0, instance_count: 0, net_count: 0, sequential_cell_count: 0 };
        },

        extract(record) {
            return (record && record.cells) ? record.cells : this.getDefault();
        },

        getCellCount(cells) {
            return cells && typeof cells.cell_count === 'number' ? cells.cell_count : 0;
        },

        getSequentialCount(cells) {
            return cells && typeof cells.sequential_cell_count === 'number' ? cells.sequential_cell_count : 0;
        }
    };

    if (global.QoRApp) {
        CellsMetric.init();
    } else {
        document.addEventListener('qorapp:ready', () => CellsMetric.init());
    }

    global.QoRCellsMetric = CellsMetric;
})(window);
