(function (global) {
    'use strict';

    const ChartsBase = {
        name: 'ui.charts-base',
        _instances: new Map(),
        _echartsAvailable: false,

        init() {
            global.QoRApp.register(this.name, this);
            this._echartsAvailable = typeof global.echarts !== 'undefined';
        },

        isAvailable() {
            return this._echartsAvailable;
        },

        create(domId, option) {
            if (!this._echartsAvailable) {
                console.warn('[ChartsBase] ECharts not available');
                return null;
            }
            const dom = document.getElementById(domId);
            if (!dom) return null;
            const chart = echarts.init(dom);
            if (option) chart.setOption(option);
            this._instances.set(domId, chart);
            return chart;
        },

        get(domId) {
            return this._instances.get(domId) || null;
        },

        update(domId, option) {
            const chart = this._instances.get(domId);
            if (chart) {
                chart.setOption(option, true);
            }
        },

        resize(domId) {
            const chart = this._instances.get(domId);
            if (chart) chart.resize();
        },

        resizeAll() {
            this._instances.forEach(c => c.resize());
        },

        dispose(domId) {
            const chart = this._instances.get(domId);
            if (chart) {
                chart.dispose();
                this._instances.delete(domId);
            }
        },

        destroy() {
            this._instances.forEach(c => c.dispose());
            this._instances.clear();
        }
    };

    if (global.QoRApp) {
        ChartsBase.init();
    } else {
        document.addEventListener('qorapp:ready', () => ChartsBase.init());
    }

    global.QoRChartsBase = ChartsBase;
})(window);
