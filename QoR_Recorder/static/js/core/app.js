/**
 * QoR Dashboard Application Core
 * 
 * 对应 JSON top_module 的顶层容器，负责：
 *  - 应用生命周期管理（初始化、销毁）
 *  - 模块注册与发现
 *  - 事件总线（模块间通信）
 *  - 全局状态协调
 * 
 * 与 dc_report.v1.json 对应关系：
 *   top_module → QoRApp (应用根)
 *   timing/area/power/... → metrics 子模块
 */
(function (global) {
    'use strict';

    const QoRApp = {
        version: '2.0.0',
        modules: new Map(),
        eventHandlers: new Map(),
        initialized: false,

        register(name, moduleImpl) {
            if (this.modules.has(name)) {
                console.warn(`[QoRApp] Module "${name}" already registered, overwriting.`);
            }
            this.modules.set(name, moduleImpl);
            console.debug(`[QoRApp] Module registered: ${name}`);
        },

        getModule(name) {
            return this.modules.get(name) || null;
        },

        on(event, handler) {
            if (!this.eventHandlers.has(event)) {
                this.eventHandlers.set(event, []);
            }
            this.eventHandlers.get(event).push(handler);
        },

        emit(event, data) {
            const handlers = this.eventHandlers.get(event);
            if (handlers) {
                handlers.forEach(h => {
                    try { h(data); } catch (e) { console.error(`[QoRApp] Event handler error for "${event}":`, e); }
                });
            }
        },

        init() {
            if (this.initialized) return;
            console.log('[QoRApp] Initializing QoR Dashboard v%s', this.version);
            this.modules.forEach((mod, name) => {
                if (typeof mod.init === 'function') {
                    try { mod.init(); } catch (e) { console.error(`[QoRApp] Failed to init module "${name}":`, e); }
                }
            });
            this.initialized = true;
            this.emit('app:ready');
        },

        destroy() {
            this.modules.forEach((mod, name) => {
                if (typeof mod.destroy === 'function') {
                    try { mod.destroy(); } catch (e) { console.error(`[QoRApp] Failed to destroy module "${name}":`, e); }
                }
            });
            this.modules.clear();
            this.eventHandlers.clear();
            this.initialized = false;
        }
    };

    global.QoRApp = QoRApp;
})(window);
