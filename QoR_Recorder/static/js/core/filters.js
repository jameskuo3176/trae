(function (global) {
    'use strict';

    const Filters = {
        name: 'filters',

        init() {
            global.QoRApp.register(this.name, this);
        },

        computeFingerprint(filters) {
            const { projectId, moduleIds, versionIds, dirPrefix } = filters;
            const mods = (moduleIds || []).slice().sort().join(',');
            const vers = (versionIds || []).slice().sort().join(',');
            return `${projectId || ''}|${mods}|${vers}|${dirPrefix || ''}`;
        },

        parseModuleValue(val) {
            const s = String(val);
            const idx = s.indexOf(':');
            if (idx > 0) {
                return { projectId: s.substring(0, idx), moduleId: s.substring(idx + 1) };
            }
            return { projectId: null, moduleId: s };
        },

        extractModuleIds(values) {
            const result = [];
            (values || []).forEach(v => {
                const parsed = this.parseModuleValue(v);
                if (parsed.moduleId && !result.includes(parsed.moduleId)) {
                    result.push(parsed.moduleId);
                }
            });
            return result;
        },

        extractProjectIds(values) {
            const result = new Set();
            (values || []).forEach(v => {
                const parsed = this.parseModuleValue(v);
                if (parsed.projectId) result.add(parsed.projectId);
            });
            return Array.from(result);
        },

        areEqual(a, b) {
            return this.computeFingerprint(a) === this.computeFingerprint(b);
        },

        normalize(input) {
            return {
                projectId: input.projectId || null,
                moduleIds: Array.isArray(input.moduleIds) ? input.moduleIds : [],
                versionIds: Array.isArray(input.versionIds) ? input.versionIds : [],
                dirPrefix: (input.dirPrefix || '').trim()
            };
        }
    };

    if (global.QoRApp) {
        Filters.init();
    } else {
        document.addEventListener('qorapp:ready', () => Filters.init());
    }

    global.QoRFilters = Filters;
})(window);
