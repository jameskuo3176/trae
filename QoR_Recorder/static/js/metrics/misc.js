(function (global) {
    'use strict';

    const MiscMetric = {
        name: 'metrics.misc',
        category: 'misc',
        schema: {
            fgcg: {
                gated_flops: { count: 'number', percentage: 'string' },
                not_gated_flops: { count: 'number', percentage: 'string' },
                total_flops: 'number',
                clock_gating_cells: 'number'
            },
            mbb_ratio: 'string',
            utilization: 'number',
            vt_ratio: 'object',
            flop_count: 'object',
            congestion: 'object',
            no_clock: 'object'
        },

        init() {
            global.QoRApp.register(this.name, this);
        },

        getDefault() {
            return {
                fgcg: {},
                mbb_ratio: '0.00%',
                utilization: 0,
                vt_ratio: {},
                flop_count: {},
                congestion: {},
                no_clock: {}
            };
        },

        extract(record) {
            if (record && record.extra) {
                return record.extra;
            }
            if (record && record.misc) {
                return record.misc;
            }
            return this.getDefault();
        },

        getGatedFlopPercentage(misc) {
            if (misc && misc.fgcg && misc.fgcg.gated_flops) {
                return misc.fgcg.gated_flops.percentage || '0%';
            }
            return '0%';
        }
    };

    if (global.QoRApp) {
        MiscMetric.init();
    } else {
        document.addEventListener('qorapp:ready', () => MiscMetric.init());
    }

    global.QoRMiscMetric = MiscMetric;
})(window);
