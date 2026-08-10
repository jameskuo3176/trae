(function (global) {
    'use strict';

    const ApiClient = {
        name: 'api-client',
        _baseURL: '/api',
        _abortControllers: new Map(),

        init() {
            global.QoRApp.register(this.name, this);
        },

        _getCSRFToken() {
            const cookie = document.cookie.split(';').find(c => c.trim().startsWith('csrftoken='));
            return cookie ? cookie.split('=')[1] : '';
        },

        async request(endpoint, options = {}) {
            const url = `${this._baseURL}${endpoint}`;
            const controllerKey = options.controllerKey || endpoint;

            if (this._abortControllers.has(controllerKey)) {
                this._abortControllers.get(controllerKey).abort();
            }
            const controller = new AbortController();
            this._abortControllers.set(controllerKey, controller);

            const defaultHeaders = {
                'Content-Type': 'application/json',
                'X-CSRFToken': this._getCSRFToken()
            };

            try {
                const response = await fetch(url, {
                    ...options,
                    headers: { ...defaultHeaders, ...(options.headers || {}) },
                    signal: controller.signal,
                    credentials: 'same-origin'
                });
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                return await response.json();
            } finally {
                this._abortControllers.delete(controllerKey);
            }
        },

        get(endpoint, options = {}) {
            return this.request(endpoint, { ...options, method: 'GET' });
        },

        post(endpoint, data, options = {}) {
            return this.request(endpoint, {
                ...options,
                method: 'POST',
                body: JSON.stringify(data)
            });
        },

        put(endpoint, data, options = {}) {
            return this.request(endpoint, {
                ...options,
                method: 'PUT',
                body: JSON.stringify(data)
            });
        },

        delete(endpoint, options = {}) {
            return this.request(endpoint, { ...options, method: 'DELETE' });
        },

        abort(controllerKey) {
            if (this._abortControllers.has(controllerKey)) {
                this._abortControllers.get(controllerKey).abort();
                this._abortControllers.delete(controllerKey);
            }
        },

        abortAll() {
            this._abortControllers.forEach(c => c.abort());
            this._abortControllers.clear();
        }
    };

    if (global.QoRApp) {
        ApiClient.init();
    } else {
        document.addEventListener('qorapp:ready', () => ApiClient.init());
    }

    global.QoRApiClient = ApiClient;
})(window);
