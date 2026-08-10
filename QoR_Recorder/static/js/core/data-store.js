(function (global) {
    'use strict';

    const DataStore = {
        name: 'data-store',
        _state: {
            projects: [],
            modules: [],
            versions: [],
            records: [],
            selectedIds: [],
            filters: {
                projectId: null,
                moduleIds: [],
                versionIds: [],
                dirPrefix: ''
            },
            loading: false,
            lastUpdated: null
        },
        _listeners: [],

        init() {
            global.QoRApp.register(this.name, this);
        },

        getState(key) {
            return key ? this._state[key] : { ...this._state };
        },

        setState(partial) {
            const old = { ...this._state };
            Object.assign(this._state, partial);
            this._notify(old, this._state);
        },

        subscribe(listener) {
            this._listeners.push(listener);
            return () => {
                this._listeners = this._listeners.filter(l => l !== listener);
            };
        },

        _notify(oldState, newState) {
            this._listeners.forEach(fn => {
                try { fn(newState, oldState); } catch (e) { console.error('[DataStore] listener error:', e); }
            });
            global.QoRApp.emit('state:change', { old: oldState, new: newState });
        },

        reset() {
            this._state = {
                projects: [],
                modules: [],
                versions: [],
                records: [],
                selectedIds: [],
                filters: { projectId: null, moduleIds: [], versionIds: [], dirPrefix: '' },
                loading: false,
                lastUpdated: null
            };
        }
    };

    if (global.QoRApp) {
        DataStore.init();
    } else {
        document.addEventListener('qorapp:ready', () => DataStore.init());
    }

    global.QoRDataStore = DataStore;
})(window);
