(function (global) {
    'use strict';

    const MODULE_REGISTRY = [
        { name: 'core.app',             path: 'core/app.js',             category: 'core',    autoInit: true },
        { name: 'core.data-store',      path: 'core/data-store.js',      category: 'core',    autoInit: true },
        { name: 'core.api-client',      path: 'core/api-client.js',      category: 'core',    autoInit: true },
        { name: 'core.filters',         path: 'core/filters.js',         category: 'core',    autoInit: true },

        { name: 'metrics.timing',       path: 'metrics/timing.js',       category: 'metrics', autoInit: true, jsonKey: 'timing' },
        { name: 'metrics.area',         path: 'metrics/area.js',         category: 'metrics', autoInit: true, jsonKey: 'area' },
        { name: 'metrics.power',        path: 'metrics/power.js',        category: 'metrics', autoInit: true, jsonKey: 'power' },
        { name: 'metrics.cells',        path: 'metrics/cells.js',        category: 'metrics', autoInit: true, jsonKey: 'cells' },
        { name: 'metrics.congestion',   path: 'metrics/congestion.js',   category: 'metrics', autoInit: true, jsonKey: 'congestion' },
        { name: 'metrics.ratios',       path: 'metrics/ratios.js',       category: 'metrics', autoInit: true, jsonKey: 'ratios' },
        { name: 'metrics.clocks',       path: 'metrics/clocks.js',       category: 'metrics', autoInit: true, jsonKey: 'clocks' },
        { name: 'metrics.frequency',    path: 'metrics/frequency.js',    category: 'metrics', autoInit: true, jsonKey: 'frequency' },
        { name: 'metrics.misc',         path: 'metrics/misc.js',         category: 'metrics', autoInit: true, jsonKey: 'misc' },

        { name: 'ui.dc-report',         path: 'ui/dc-report.js',         category: 'ui',      autoInit: true },
        { name: 'ui.charts-base',       path: 'ui/charts-base.js',       category: 'ui',      autoInit: true },
        { name: 'ui.violation-panel',   path: 'ui/violation-panel.js',   category: 'ui',      autoInit: true },
        { name: 'ui.config-manager',    path: 'ui/config-manager.js',    category: 'ui',      autoInit: true }
    ];

    const ModuleIndex = {
        name: 'module-index',
        baseUrl: '/static/js',

        getAll() {
            return MODULE_REGISTRY.slice();
        },

        getByCategory(category) {
            return MODULE_REGISTRY.filter(m => m.category === category);
        },

        getMetricsModules() {
            return this.getByCategory('metrics');
        },

        getCoreModules() {
            return this.getByCategory('core');
        },

        getUIModules() {
            return this.getByCategory('ui');
        },

        getJsonKeyMap() {
            const map = {};
            MODULE_REGISTRY.filter(m => m.jsonKey).forEach(m => {
                map[m.jsonKey] = m.name;
            });
            return map;
        },

        getScriptTags() {
            return MODULE_REGISTRY.map(m => `${this.baseUrl}/${m.path}`);
        },

        loadAll() {
            return new Promise((resolve, reject) => {
                const scripts = this.getScriptTags();
                let loaded = 0;
                const errors = [];
                scripts.forEach(src => {
                    const s = document.createElement('script');
                    s.src = src;
                    s.onload = () => {
                        loaded++;
                        if (loaded === scripts.length) {
                            if (errors.length) reject(errors);
                            else resolve();
                        }
                    };
                    s.onerror = () => {
                        errors.push(src);
                        loaded++;
                        if (loaded === scripts.length) reject(errors);
                    };
                    document.head.appendChild(s);
                });
            });
        },

        printStructure() {
            console.group('QoR Dashboard Module Structure');
            console.log('Core modules:');
            this.getCoreModules().forEach(m => console.log(`  - ${m.name} (${m.path})`));
            console.log('Metrics modules (mapped to JSON top_module keys):');
            this.getMetricsModules().forEach(m => console.log(`  - ${m.name} ← JSON["${m.jsonKey}"]`));
            console.log('UI modules:');
            this.getUIModules().forEach(m => console.log(`  - ${m.name} (${m.path})`));
            console.groupEnd();
        }
    };

    global.QoRModuleIndex = ModuleIndex;

    if (global.QoRApp) {
        global.QoRApp.register('module-index', ModuleIndex);
    }
})(window);
