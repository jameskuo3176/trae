(function (global) {
    'use strict';

    const ConfigManager = {
        name: 'ui.config-manager',
        _defaults: {
            chartHeight: 400,
            pageSize: 50,
            autoRefresh: false,
            refreshInterval: 30000,
            theme: 'light'
        },
        _config: {},
        _storageKey: 'qor_dashboard_config',

        init() {
            global.QoRApp.register(this.name, this);
            this._load();
        },

        _load() {
            try {
                const stored = localStorage.getItem(this._storageKey);
                this._config = stored ? { ...this._defaults, ...JSON.parse(stored) } : { ...this._defaults };
            } catch (e) {
                this._config = { ...this._defaults };
            }
        },

        _save() {
            try {
                localStorage.setItem(this._storageKey, JSON.stringify(this._config));
            } catch (e) { /* ignore */ }
        },

        get(key) {
            return key ? this._config[key] : { ...this._config };
        },

        set(key, value) {
            this._config[key] = value;
            this._save();
            global.QoRApp.emit('config:change', { key, value });
        },

        reset() {
            this._config = { ...this._defaults };
            this._save();
            global.QoRApp.emit('config:reset');
        },

        getAll() {
            return { ...this._config };
        }
    };

    if (global.QoRApp) {
        ConfigManager.init();
    } else {
        document.addEventListener('qorapp:ready', () => ConfigManager.init());
    }

    global.QoRConfigManager = ConfigManager;
})(window);
