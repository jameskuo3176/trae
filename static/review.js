// QoR Recorder - Review Page Logic
(function () {
    'use strict';

    // ==================== 全局状态 ====================
    const IS_ADMIN = window.REVIEW_CONFIG.isAdmin;
    const CURRENT_USER_ID = window.REVIEW_CONFIG.userId;
    let OPTIONS = { projects: [], approved_tile_reviews: [], approved_group_reviews: [] };
    let CURRENT_TAB = 'tile';
    let CURRENT_REVIEW_ID = null;
    let CURRENT_REVIEW_TYPE = null;
    let UPLOAD_SNAP_ID = null;

    // ==================== 工具 ====================
    const $ = (s) => document.querySelector(s);
    const $$ = (s) => Array.from(document.querySelectorAll(s));
    function escapeHtml(s) {
        if (s === null || s === undefined) return '';
        return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
    }
    function safeArr(v) { return Array.isArray(v) ? v : []; }
    function fmtTime(s) {
        if (!s) return '-';
        const d = new Date(s);
        if (isNaN(d.getTime())) return s;
        return d.toLocaleString('zh-CN', { hour12: false });
    }
    function statusPill(s) { return `<span class="status-pill status-${s}">${s}</span>`; }
    function verdictPill(v) { return v ? `<span class="verdict-pill verdict-${v}">${v}</span>` : ''; }

    // ==================== 初始化 ====================
    async function loadOptions() {
        try {
            const r = await fetch('/api/reviews/options');
            OPTIONS = await r.json();
            const sel = $('#projectFilter');
            sel.innerHTML = '<option value="">-- 全部 --</option>' +
                OPTIONS.projects.map(p => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join('');
        } catch (e) { console.error('loadOptions failed', e); }
    }

    // ==================== Tab 切换 ====================
    function switchTab(tab) {
        CURRENT_TAB = tab;
        $$('.review-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
        $('#newBtn').textContent =
            tab === 'snapshot' ? '+ 新建 Snapshot' : `+ 新建 ${({ tile: 'Tile', group: 'Group', subsystem: 'Subsystem' })[tab]} Review`;
        loadActiveTab();
    }

    function loadActiveTab() {
        if (CURRENT_TAB === 'tile') loadReviews('tile');
        else if (CURRENT_TAB === 'group') loadReviews('group');
        else if (CURRENT_TAB === 'subsystem') loadReviews('subsystem');
        else if (CURRENT_TAB === 'snapshot') loadSnapshots();
    }

    function activeFilters() {
        return {
            project_id: $('#projectFilter').value,
            status: $('#statusFilter').value,
            verdict: $('#verdictFilter').value,
        };
    }

    async function loadReviews(type) {
        const f = activeFilters();
        const qs = new URLSearchParams();
        if (f.project_id) qs.set('project_id', f.project_id);
        if (f.status) qs.set('status', f.status);
        try {
            const r = await fetch(`/api/reviews/${type}?` + qs.toString());
            const data = await r.json();
            let items = safeArr(data.items);
            if (f.verdict) items = items.filter(x => x.verdict === f.verdict);
            $(`#cnt-${type}`).textContent = items.length;
            renderCards(items.map(x => { x._type = type; return renderReviewCard(x); }));
        } catch (e) {
            console.error('loadReviews failed', e);
            $('#listContainer').innerHTML = '<div class="empty-state">加载失败, 请刷新重试</div>';
        }
    }

    async function loadSnapshots() {
        const f = activeFilters();
        const qs = new URLSearchParams();
        if (f.project_id) qs.set('project_id', f.project_id);
        try {
            const r = await fetch('/api/reviews/snapshot?' + qs.toString());
            const data = await r.json();
            const items = safeArr(data.items);
            $('#cnt-snapshot').textContent = items.length;
            renderCards(items.map(renderSnapshotCard));
        } catch (e) {
            console.error('loadSnapshots failed', e);
            $('#listContainer').innerHTML = '<div class="empty-state">加载失败, 请刷新重试</div>';
        }
    }

    function renderCards(cards) {
        const c = $('#listContainer');
        if (!cards.length) {
            const tabName = ({ tile: 'Tile', group: 'Group', subsystem: 'Subsystem', snapshot: 'Snapshot' })[CURRENT_TAB];
            c.innerHTML = `<div class="empty-state">
                <div style="font-size: 14px;">暂无 ${tabName} 数据</div>
                <div class="hint">点击右上角 "<b>+ 新建</b>" 创建第一条 ${tabName}</div>
            </div>`;
            return;
        }
        c.innerHTML = cards.join('');
    }

    // ==================== Review 卡片渲染 ====================
    function renderReviewCard(r) {
        const t = r._type || 'tile';
        const isOwner = r.created_by === CURRENT_USER_ID;
        const isParticipant = isOwner || r.leader_id === CURRENT_USER_ID || r.manager_id === CURRENT_USER_ID;
        const isEditable = (IS_ADMIN || isParticipant) && (r.status === 'draft' || r.status === 'rejected');
        const canSubmit = isEditable;
        const canReview = r.status === 'submitted' && (IS_ADMIN || !isParticipant);
        const canDelete = isEditable && !['submitted', 'approved', 'frozen'].includes(r.status);

        const kmCount = safeArr(r.key_metrics).length;
        const fiCount = safeArr(r.findings).length;
        const deCount = safeArr(r.decisions).length;
        const nsCount = safeArr(r.next_steps).length;
        const rkCount = safeArr(r.risks).length;
        const tileIds = safeArr(r.tile_review_ids).length;
        const grpIds = safeArr(r.group_review_ids).length;

        const meta = [];
        if (r.project_name) meta.push(`<span class="m">📁 ${escapeHtml(r.project_name)}</span>`);
        if (r.module_name) meta.push(`<span class="m">📦 ${escapeHtml(r.module_name)}</span>`);
        if (r.group_name) meta.push(`<span class="m">👥 ${escapeHtml(r.group_name)}</span>`);
        if (r.subsystem) meta.push(`<span class="m">🧩 ${escapeHtml(r.subsystem)}</span>`);
        meta.push(`<span class="m">👤 ${escapeHtml(r.created_by_name || r.leader_name || r.manager_name || '?')}</span>`);
        meta.push(`<span class="m">🕒 ${fmtTime(r.created_at)}</span>`);
        if (tileIds) meta.push(`<span class="m">🔗 Tile×${tileIds}</span>`);
        if (grpIds) meta.push(`<span class="m">🔗 Group×${grpIds}</span>`);

        const tags = [];
        if (kmCount) tags.push(`<span class="m">📊 指标 ${kmCount}</span>`);
        if (fiCount) tags.push(`<span class="m">🔍 发现 ${fiCount}</span>`);
        if (deCount) tags.push(`<span class="m">⚖ 决策 ${deCount}</span>`);
        if (nsCount) tags.push(`<span class="m">➡ 后续 ${nsCount}</span>`);
        if (rkCount) tags.push(`<span class="m">⚠ 风险 ${rkCount}</span>`);

        const summary = r.summary ? `<div class="rc-summary">${escapeHtml(r.summary)}</div>` : '';
        const tagsHtml = tags.length ? `<div class="rc-meta rc-tags">${tags.join('')}</div>` : '';

        return `<div class="review-card status-${escapeHtml(r.status)}">
            <div class="rc-head">
                <div class="rc-title">${escapeHtml(r.title)} <span style="color:var(--color-text-secondary); font-weight:normal; font-size:11px;">#${r.id}</span></div>
                <div style="display:flex; gap:4px; flex-shrink:0;">${statusPill(r.status)} ${verdictPill(r.verdict)}</div>
            </div>
            <div class="rc-meta">${meta.join('')}</div>
            ${summary}
            ${tagsHtml}
            <div class="rc-actions">
                <button class="btn-sm" onclick="Review.viewDetail('${t}', ${r.id})">详情</button>
                ${isEditable ? `<button class="btn-sm" onclick="Review.openEditModal('${t}', ${r.id})">编辑</button>` : ''}
                ${canSubmit ? `<button class="btn-sm" onclick="Review.doAction('/api/reviews/${t}/${r.id}/submit','POST',null)">提交</button>` : ''}
                ${canReview ? `<button class="btn-sm" onclick="Review.openReviewActionModal('${t}', ${r.id})">审核</button>` : ''}
                ${canDelete ? `<button class="btn-sm btn-danger" onclick="Review.doDelete('${t}', ${r.id})">删除</button>` : ''}
            </div>
        </div>`;
    }

    // ==================== Snapshot 卡片渲染 ====================
    function renderSnapshotCard(s) {
        const fileCount = s.file_count || 0;
        const meta = [
            `<span class="m">📁 ${escapeHtml(s.project_name || ('#' + s.project_id))}</span>`,
            `<span class="m">🏷 ${escapeHtml(s.snapshot_type || '-')}</span>`,
            `<span class="m">👤 ${escapeHtml(s.created_by_name || '?')}</span>`,
            `<span class="m">🕒 ${fmtTime(s.created_at)}</span>`,
            `<span class="m">📦 ${s.record_count || 0} 记录</span>`,
            `<span class="m">📎 ${fileCount} 文件</span>`,
        ];
        const verified = s.verified
            ? '<span style="color:#2e7d32; font-weight:600;">✓ 校验通过</span>'
            : '<span style="color:#c62828; font-weight:600;">✗ 已篡改</span>';
        return `<div class="review-card status-frozen">
            <div class="rc-head">
                <div class="rc-title">${escapeHtml(s.name)} <span style="color:var(--color-text-secondary); font-weight:normal; font-size:11px;">#${s.id}</span></div>
                <div style="flex-shrink:0;">${statusPill('frozen')}</div>
            </div>
            <div class="rc-meta">${meta.join('')}</div>
            ${s.description ? `<div class="rc-summary">${escapeHtml(s.description)}</div>` : ''}
            <div class="rc-meta" style="font-size: 11px;">${verified} &nbsp;|&nbsp; sha256: <code style="font-size: 10px;">${escapeHtml((s.checksum || '').slice(0, 16))}…</code></div>
            <div class="rc-actions">
                <button class="btn-sm" onclick="Review.viewSnapshot(${s.id})">查看</button>
                ${IS_ADMIN ? `<button class="btn-sm" onclick="Review.openUploadModal(${s.id})">上传附件</button>` : ''}
                ${IS_ADMIN ? `<button class="btn-sm btn-danger" onclick="Review.deleteSnapshot(${s.id})">删除</button>` : ''}
            </div>
        </div>`;
    }

    // ==================== 通用操作 ====================
    async function doAction(url, method, body) {
        const opt = { method, headers: {} };
        if (body) {
            opt.headers['Content-Type'] = 'application/json';
            opt.body = JSON.stringify(body);
        }
        const r = await fetch(url, opt);
        const data = await r.json();
        if (!r.ok) { alert('操作失败: ' + (data.error || r.status)); return; }
        loadActiveTab();
    }
    async function doDelete(type, id) {
        if (!confirm('确定删除?')) return;
        const r = await fetch(`/api/reviews/${type}/${id}`, { method: 'DELETE' });
        const data = await r.json();
        if (!r.ok) { alert('删除失败: ' + (data.error || r.status)); return; }
        loadActiveTab();
    }

    // ==================== 表单弹窗 ====================
    function openCreateModal() {
        if (CURRENT_TAB === 'snapshot') return openCreateSnapshotModal();
        CURRENT_REVIEW_ID = null;
        $('#modalTitle').textContent = {
            tile: '新建 Tile Review',
            group: '新建 Group Review',
            subsystem: '新建 Subsystem Review',
        }[CURRENT_TAB];
        $('#formBody').innerHTML = buildFormHtml(CURRENT_TAB, {});
        initFormListRows({});
        $('#formModal').classList.add('show');
    }

    function openEditModal(type, id) {
        CURRENT_REVIEW_ID = id;
        $('#modalTitle').textContent = `编辑 ${type} Review #${id}`;
        fetch(`/api/reviews/${type}/${id}`).then(r => r.json()).then(item => {
            if (item.error) { alert(item.error); return; }
            $('#formBody').innerHTML = buildFormHtml(type, item, true);
            initFormListRows(item);
            if (type === 'tile' && item.project_id) {
                onFormProjectChange('tile');
                setTimeout(() => {
                    if (item.module_id) $('#formModule').value = item.module_id;
                    if (item.record_id) $('#formRecord').value = item.record_id;
                }, 0);
            } else if (type === 'group' && item.project_id) {
                onFormProjectChange('group');
                setTimeout(() => {
                    $$('#formTileIds option').forEach(o => {
                        if (safeArr(item.tile_review_ids).includes(parseInt(o.value, 10))) o.selected = true;
                    });
                }, 0);
            } else if (type === 'subsystem' && item.project_id) {
                onFormProjectChange('subsystem');
                setTimeout(() => {
                    $$('#formGroupIds option').forEach(o => {
                        if (safeArr(item.group_review_ids).includes(parseInt(o.value, 10))) o.selected = true;
                    });
                }, 0);
            }
            $('#formModal').classList.add('show');
        });
    }

    function initFormListRows(item) {
        rebuildListRow('kmList', safeArr(item.key_metrics), 'km');
        rebuildListRow('findingList', safeArr(item.findings), 'text');
        rebuildListRow('decisionList', safeArr(item.decisions), 'dec');
        rebuildListRow('nextStepList', safeArr(item.next_steps), 'dec');
        rebuildListRow('riskList', safeArr(item.risks), 'risk');
    }

    function closeFormModal() { $('#formModal').classList.remove('show'); }

    function buildFormHtml(type, item, isEdit) {
        const projOpts = OPTIONS.projects.map(p =>
            `<option value="${p.id}" ${item.project_id === p.id ? 'selected' : ''}>${escapeHtml(p.name)}</option>`
        ).join('');
        const verdictOpts = ['', 'pass', 'concern', 'blocked'].map(v =>
            `<option value="${v}" ${(item.verdict || '') === v ? 'selected' : ''}>${v || '-- 暂无 --'}</option>`
        ).join('');

        const detailBlock = `
            <h3>关键指标 (目标 / 实际 / Δ / 状态)</h3>
            <div class="row-header km"><div>指标</div><div>目标</div><div>实际</div><div>Δ</div><div>状态</div><div></div></div>
            <div id="kmList"></div>
            <button class="btn-sm" type="button" onclick="Review.addKmRow()">+ 添加指标</button>

            <h3>关键发现 (短句列表)</h3>
            <div id="findingList"></div>
            <button class="btn-sm" type="button" onclick="Review.addTextRow('findingList')">+ 添加</button>

            <h3>待决策项 (项目 / Owner / Due)</h3>
            <div class="row-header dec"><div>项目</div><div>Owner</div><div>Due</div><div></div></div>
            <div id="decisionList"></div>
            <button class="btn-sm" type="button" onclick="Review.addDecRow('decisionList')">+ 添加</button>

            <h3>后续计划 (动作 / Owner / Due)</h3>
            <div id="nextStepList"></div>
            <button class="btn-sm" type="button" onclick="Review.addDecRow('nextStepList')">+ 添加</button>

            <h3>风险 / 行动项 (风险 / 行动 / Owner)</h3>
            <div class="row-header risk"><div>风险</div><div>行动</div><div>Owner</div><div></div></div>
            <div id="riskList"></div>
            <button class="btn-sm" type="button" onclick="Review.addRiskRow()">+ 添加</button>
        `;

        if (type === 'tile') return `
            <div class="form-grid-2">
                <div class="form-row">
                    <label>项目 *</label>
                    <select id="formProject" onchange="Review.onFormProjectChange('tile')" ${isEdit ? 'disabled' : ''}>
                        <option value="">-- 请选择 --</option>${projOpts}
                    </select>
                </div>
                <div class="form-row">
                    <label>模块 *</label>
                    <select id="formModule" ${isEdit ? 'disabled' : ''}><option value="">-- 先选项目 --</option></select>
                </div>
            </div>
            <div class="form-row">
                <label>关联 QoR 记录 (可选, 自动快照指标)</label>
                <select id="formRecord"><option value="">-- 不关联 --</option></select>
            </div>
            <div class="form-row">
                <label>标题 *</label>
                <input type="text" id="formTitle" value="${escapeHtml(item.title || '')}" placeholder="例: W35 ALU 单元 review">
            </div>
            <div class="form-grid-2">
                <div class="form-row">
                    <label>周期</label>
                    <select id="formPeriod">
                        <option value="weekly" ${item.period === 'weekly' ? 'selected' : ''}>weekly</option>
                        <option value="daily" ${item.period === 'daily' ? 'selected' : ''}>daily</option>
                        <option value="adhoc" ${item.period === 'adhoc' ? 'selected' : ''}>adhoc</option>
                    </select>
                </div>
                <div class="form-row">
                    <label>总体结论 (verdict)</label>
                    <select id="formVerdict">${verdictOpts}</select>
                </div>
            </div>
            <div class="form-row">
                <label>总结</label>
                <textarea id="formSummary" placeholder="本周本模块的总体评价、瓶颈、关注点...">${escapeHtml(item.summary || '')}</textarea>
            </div>
            ${detailBlock}
        `;

        if (type === 'group') return `
            <div class="form-grid-2">
                <div class="form-row">
                    <label>项目 *</label>
                    <select id="formProject" onchange="Review.onFormProjectChange('group')">
                        <option value="">-- 请选择 --</option>${projOpts}
                    </select>
                </div>
                <div class="form-row">
                    <label>Group 名 * (如 CPU/GPU/MEM)</label>
                    <input type="text" id="formGroupName" value="${escapeHtml(item.group_name || '')}">
                </div>
            </div>
            <div class="form-row">
                <label>标题</label>
                <input type="text" id="formTitle" value="${escapeHtml(item.title || '')}">
            </div>
            <div class="form-grid-2">
                <div class="form-row">
                    <label>周期</label>
                    <select id="formPeriod">
                        <option value="weekly" ${item.period === 'weekly' ? 'selected' : ''}>weekly</option>
                        <option value="daily" ${item.period === 'daily' ? 'selected' : ''}>daily</option>
                    </select>
                </div>
                <div class="form-row">
                    <label>总体结论 (verdict)</label>
                    <select id="formVerdict">${verdictOpts}</select>
                </div>
            </div>
            <div class="form-row">
                <label>选择已 approved 的 Tile Reviews * (按住 Ctrl/⌘ 多选)</label>
                <select id="formTileIds" multiple size="6" style="height:auto; min-height:120px;"></select>
            </div>
            <div class="form-row">
                <label>总结</label>
                <textarea id="formSummary">${escapeHtml(item.summary || '')}</textarea>
            </div>
            ${detailBlock}
        `;

        if (type === 'subsystem') return `
            <div class="form-grid-2">
                <div class="form-row">
                    <label>项目 *</label>
                    <select id="formProject" onchange="Review.onFormProjectChange('subsystem')">
                        <option value="">-- 请选择 --</option>${projOpts}
                    </select>
                </div>
                <div class="form-row">
                    <label>Subsystem * (如 TOP/IO/ANALOG)</label>
                    <input type="text" id="formSubsystem" value="${escapeHtml(item.subsystem || '')}">
                </div>
            </div>
            <div class="form-row">
                <label>标题</label>
                <input type="text" id="formTitle" value="${escapeHtml(item.title || '')}">
            </div>
            <div class="form-grid-2">
                <div class="form-row">
                    <label>周期</label>
                    <select id="formPeriod">
                        <option value="weekly" ${item.period === 'weekly' ? 'selected' : ''}>weekly</option>
                    </select>
                </div>
                <div class="form-row">
                    <label>总体结论 (verdict)</label>
                    <select id="formVerdict">${verdictOpts}</select>
                </div>
            </div>
            <div class="form-row">
                <label>选择已 approved 的 Group Reviews * (按住 Ctrl/⌘ 多选)</label>
                <select id="formGroupIds" multiple size="6" style="height:auto; min-height:120px;"></select>
            </div>
            <div class="form-row">
                <label>总结</label>
                <textarea id="formSummary">${escapeHtml(item.summary || '')}</textarea>
            </div>
            ${detailBlock}
        `;
        return '';
    }

    function onFormProjectChange(type) {
        const pid = parseInt(($('#formProject') || {}).value || '0', 10);
        if (type === 'tile') {
            const proj = OPTIONS.projects.find(p => p.id === pid);
            const modSel = $('#formModule');
            modSel.innerHTML = '<option value="">-- 请选择 --</option>' +
                (proj ? proj.modules.map(m => `<option value="${m.id}">${escapeHtml(m.name)}</option>`).join('') : '');
            modSel.onchange = function () {
                const mid = parseInt(modSel.value || '0', 10);
                const m = proj ? proj.modules.find(x => x.id === mid) : null;
                $('#formRecord').innerHTML = '<option value="">-- 不关联 --</option>' +
                    (m ? m.records.map(r => `<option value="${r.id}">${escapeHtml(r.version || '')}</option>`).join('') : '');
            };
        } else if (type === 'group') {
            const tilesForProj = OPTIONS.approved_tile_reviews.filter(t => t.project_id === pid);
            $('#formTileIds').innerHTML = tilesForProj.map(t =>
                `<option value="${t.id}">#${t.id} ${escapeHtml(t.title)} - ${escapeHtml(t.module_name || '')}</option>`
            ).join('');
        } else if (type === 'subsystem') {
            const groupsForProj = OPTIONS.approved_group_reviews.filter(g => g.project_id === pid);
            $('#formGroupIds').innerHTML = groupsForProj.map(g =>
                `<option value="${g.id}">#${g.id} ${escapeHtml(g.title)} - [${escapeHtml(g.group_name)}]</option>`
            ).join('');
        } else if (type === 'snapshot') {
            fetch(`/api/reviews/subsystem?project_id=${pid}&status=approved`).then(r => r.json()).then(d => {
                $('#formSubsystemReview').innerHTML = '<option value="">-- 自定义快照 --</option>' +
                    safeArr(d.items).map(x => `<option value="${x.id}">#${x.id} ${escapeHtml(x.title)} [${escapeHtml(x.subsystem)}]</option>`).join('');
            });
        }
    }

    // ==================== 列表行构造 ====================
    function addTextRow(containerId, value) {
        const list = $('#' + containerId);
        const row = document.createElement('div');
        row.className = 'list-row';
        row.innerHTML = `<input type="text" value="${escapeHtml(value || '')}" placeholder="请输入..."><button class="btn-sm btn-danger del" type="button" onclick="this.parentNode.remove()">×</button>`;
        list.appendChild(row);
    }
    function addDecRow(containerId, obj) {
        const list = $('#' + containerId);
        const row = document.createElement('div');
        row.className = 'dec-row';
        const v = obj || {};
        row.innerHTML = `
            <input type="text" placeholder="项目/动作" value="${escapeHtml(v.item || v.action || v.text || '')}">
            <input type="text" placeholder="Owner" value="${escapeHtml(v.owner || '')}">
            <input type="text" placeholder="Due (YYYY-MM-DD)" value="${escapeHtml(v.due || '')}">
            <button class="btn-sm btn-danger del" type="button" onclick="this.parentNode.remove()">×</button>`;
        list.appendChild(row);
    }
    function addKmRow(obj) {
        const list = $('#kmList');
        const row = document.createElement('div');
        row.className = 'km-row';
        const v = obj || {};
        const st = v.status || '';
        row.innerHTML = `
            <input type="text" placeholder="指标名" value="${escapeHtml(v.name || v.metric || '')}">
            <input type="text" placeholder="目标" value="${escapeHtml(v.target != null ? String(v.target) : '')}">
            <input type="text" placeholder="实际" value="${escapeHtml(v.actual != null ? String(v.actual) : '')}">
            <input type="text" placeholder="Δ" value="${escapeHtml(v.delta != null ? String(v.delta) : '')}">
            <select>
                <option value="" ${st === '' ? 'selected' : ''}>--</option>
                <option value="good" ${st === 'good' ? 'selected' : ''}>good</option>
                <option value="warn" ${st === 'warn' ? 'selected' : ''}>warn</option>
                <option value="bad"  ${st === 'bad' ? 'selected' : ''}>bad</option>
            </select>
            <button class="btn-sm btn-danger del" type="button" onclick="this.parentNode.remove()">×</button>`;
        list.appendChild(row);
    }
    function addRiskRow(obj) {
        const list = $('#riskList');
        const row = document.createElement('div');
        row.className = 'risk-row';
        const v = obj || {};
        row.innerHTML = `
            <input type="text" placeholder="风险描述" value="${escapeHtml(v.risk || v.text || '')}">
            <input type="text" placeholder="行动" value="${escapeHtml(v.action || '')}">
            <input type="text" placeholder="负责人" value="${escapeHtml(v.owner || '')}">
            <button class="btn-sm btn-danger del" type="button" onclick="this.parentNode.remove()">×</button>`;
        list.appendChild(row);
    }

    function rebuildListRow(containerId, items, kind) {
        const list = $('#' + containerId);
        if (!list) return;
        list.innerHTML = '';
        if (!items.length) {
            if (kind === 'km') addKmRow();
            else if (kind === 'text') addTextRow(containerId);
            else if (kind === 'dec') addDecRow(containerId);
            else if (kind === 'risk') addRiskRow();
            return;
        }
        items.forEach(x => {
            if (kind === 'km') addKmRow(x);
            else if (kind === 'text') addTextRow(containerId, typeof x === 'string' ? x : (x.text || x.finding || ''));
            else if (kind === 'dec') addDecRow(containerId, x);
            else if (kind === 'risk') addRiskRow(x);
        });
    }

    function collectKeyMetrics() {
        const out = [];
        $$('#kmList .km-row').forEach(row => {
            const inputs = row.querySelectorAll('input');
            const sel = row.querySelector('select');
            const name = inputs[0].value.trim();
            const target = inputs[1].value.trim();
            const actual = inputs[2].value.trim();
            const delta = inputs[3].value.trim();
            const status = sel.value;
            if (name || target || actual || delta) out.push({ name, target, actual, delta, status });
        });
        return out;
    }
    function collectTextList(containerId) {
        const out = [];
        $$('#' + containerId + ' .list-row input').forEach(inp => { const v = inp.value.trim(); if (v) out.push(v); });
        return out;
    }
    function collectDecList(containerId) {
        const out = [];
        $$('#' + containerId + ' .dec-row').forEach(row => {
            const inputs = row.querySelectorAll('input');
            const item = inputs[0].value.trim();
            const owner = inputs[1].value.trim();
            const due = inputs[2].value.trim();
            if (item || owner || due) out.push({ item, owner, due });
        });
        return out;
    }
    function collectRisks() {
        const out = [];
        $$('#riskList .risk-row').forEach(row => {
            const inputs = row.querySelectorAll('input');
            const risk = inputs[0].value.trim();
            const action = inputs[1].value.trim();
            const owner = inputs[2].value.trim();
            if (risk || action || owner) out.push({ risk, action, owner });
        });
        return out;
    }

    async function submitForm() {
        const type = CURRENT_TAB;
        if (type === 'snapshot') return submitSnapshotForm();
        const project_id = parseInt($('#formProject').value || '0', 10);
        if (!project_id) return alert('请选择项目');
        const body = {
            project_id,
            verdict: ($('#formVerdict') || {}).value || null,
            key_metrics: collectKeyMetrics(),
            findings: collectTextList('findingList'),
            decisions: collectDecList('decisionList'),
            next_steps: collectDecList('nextStepList'),
            risks: collectRisks(),
        };
        if (type === 'tile') {
            body.module_id = parseInt($('#formModule').value || '0', 10);
            if (!body.module_id) return alert('请选择模块');
            body.record_id = parseInt($('#formRecord').value || '0', 10) || null;
            body.title = $('#formTitle').value;
            body.period = $('#formPeriod').value;
            body.summary = $('#formSummary').value;
        } else if (type === 'group') {
            body.group_name = $('#formGroupName').value;
            if (!body.group_name) return alert('请填写 Group 名');
            body.title = $('#formTitle').value;
            body.period = $('#formPeriod').value;
            body.summary = $('#formSummary').value;
            body.tile_review_ids = $$('#formTileIds option:checked').map(o => parseInt(o.value, 10));
            if (!body.tile_review_ids.length) return alert('请至少选择一个 Tile Review');
        } else if (type === 'subsystem') {
            body.subsystem = $('#formSubsystem').value;
            if (!body.subsystem) return alert('请填写 Subsystem');
            body.title = $('#formTitle').value;
            body.period = $('#formPeriod').value;
            body.summary = $('#formSummary').value;
            body.group_review_ids = $$('#formGroupIds option:checked').map(o => parseInt(o.value, 10));
            if (!body.group_review_ids.length) return alert('请至少选择一个 Group Review');
        }
        const url = CURRENT_REVIEW_ID ? `/api/reviews/${type}/${CURRENT_REVIEW_ID}` : `/api/reviews/${type}`;
        const method = CURRENT_REVIEW_ID ? 'PUT' : 'POST';
        const r = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        const data = await r.json();
        if (!r.ok) return alert('保存失败: ' + (data.error || r.status));
        closeFormModal();
        loadActiveTab();
    }

    // ==================== 审核弹窗 ====================
    function openReviewActionModal(type, id) {
        CURRENT_REVIEW_TYPE = type;
        CURRENT_REVIEW_ID = id;
        $('#reviewActionTitle').textContent = `审核 ${type} Review #${id}`;
        $('#reviewActionComment').value = '';
        $('#reviewActionModal').classList.add('show');
    }
    function closeReviewActionModal() { $('#reviewActionModal').classList.remove('show'); }
    async function doReview(action) {
        const url = `/api/reviews/${CURRENT_REVIEW_TYPE}/${CURRENT_REVIEW_ID}/review`;
        const r = await fetch(url, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action, comment: $('#reviewActionComment').value })
        });
        const data = await r.json();
        if (!r.ok) return alert('审核失败: ' + (data.error || r.status));
        closeReviewActionModal();
        loadActiveTab();
    }

    // ==================== 详情弹窗 ====================
    async function viewDetail(type, id) {
        const r = await fetch(`/api/reviews/${type}/${id}`);
        const item = await r.json();
        if (!r.ok) return alert('加载失败: ' + (item.error || r.status));
        renderDetailModal(item, type);
    }
    function closeDetailModal() { $('#detailModal').classList.remove('show'); }

    function renderKeyMetricsTable(items) {
        if (!items || !items.length) return '';
        const rows = items.map(x => {
            const name = escapeHtml(x.name || x.metric || '');
            const target = (x.target !== undefined && x.target !== null) ? escapeHtml(String(x.target)) : '-';
            const actual = (x.actual !== undefined && x.actual !== null) ? escapeHtml(String(x.actual)) : '-';
            let deltaCls = '', deltaStr = '-';
            if (x.delta !== undefined && x.delta !== null && x.delta !== '') {
                const n = parseFloat(x.delta);
                if (!isNaN(n)) {
                    deltaStr = (n >= 0 ? '+' : '') + n;
                    if (x.status === 'good') deltaCls = 'delta-good';
                    else if (x.status === 'bad') deltaCls = 'delta-bad';
                    else if (x.status === 'warn') deltaCls = 'delta-warn';
                } else { deltaStr = escapeHtml(String(x.delta)); }
            }
            const unit = x.unit ? ` <span style="color:var(--color-text-secondary); font-size:11px;">${escapeHtml(x.unit)}</span>` : '';
            return `<tr><td>${name}${unit}</td><td class="num">${target}</td><td class="num">${actual}</td><td class="num ${deltaCls}">${deltaStr}</td></tr>`;
        }).join('');
        return `<table class="key-metrics-table"><thead><tr><th>指标</th><th class="num">目标</th><th class="num">实际</th><th class="num">Δ</th></tr></thead><tbody>${rows}</tbody></table>`;
    }

    function renderDetailModal(r) {
        $('#detailTitle').textContent = r.title || ('Review #' + r.id);
        const kpis = safeArr(r.key_metrics);
        const findings = safeArr(r.findings);
        const decisions = safeArr(r.decisions);
        const nextSteps = safeArr(r.next_steps);
        const risks = safeArr(r.risks);
        const tileIds = safeArr(r.tile_review_ids);
        const grpIds = safeArr(r.group_review_ids);

        const list = (arr, map) => arr.length
            ? `<ul class="bullet-list">${arr.map(map).join('')}</ul>`
            : '<i style="color:var(--color-text-secondary); font-size:12px;">无</i>';
        const findingsHtml = list(findings, x => `<li>${escapeHtml(typeof x === 'string' ? x : (x.text || x.finding || JSON.stringify(x)))}</li>`);
        const decisionsHtml = list(decisions, x => {
            const item = typeof x === 'string' ? x : (x.item || x.text || '');
            const owner = (x && x.owner) ? ` <span style="color:var(--color-text-secondary); font-size:11px;">[Owner: ${escapeHtml(x.owner)}]</span>` : '';
            const due = (x && x.due) ? ` <span style="color:var(--color-text-secondary); font-size:11px;">[Due: ${escapeHtml(x.due)}]</span>` : '';
            return `<li>${escapeHtml(item)}${owner}${due}</li>`;
        });
        const nextStepsHtml = list(nextSteps, x => {
            const action = typeof x === 'string' ? x : (x.action || x.text || '');
            const owner = (x && x.owner) ? ` <span style="color:var(--color-text-secondary); font-size:11px;">[Owner: ${escapeHtml(x.owner)}]</span>` : '';
            const due = (x && x.due) ? ` <span style="color:var(--color-text-secondary); font-size:11px;">[Due: ${escapeHtml(x.due)}]</span>` : '';
            return `<li>${escapeHtml(action)}${owner}${due}</li>`;
        });
        const risksHtml = risks.length
            ? `<ul class="risk-list">${risks.map(x => {
                const risk = typeof x === 'string' ? x : (x.risk || x.text || '');
                const action = (x && x.action) ? `<span class="risk-a">→ ${escapeHtml(x.action)}</span>` : '';
                const owner = (x && x.owner) ? `<span class="risk-o">${escapeHtml(x.owner)}</span>` : '';
                return `<li><span class="risk-r">${escapeHtml(risk)}</span>${action} ${owner}</li>`;
            }).join('')}</ul>`
            : '<i style="color:var(--color-text-secondary); font-size:12px;">无</i>';

        $('#detailBody').innerHTML = `
            <div style="margin-bottom: 12px;">${statusPill(r.status)} ${verdictPill(r.verdict)}
                <span style="font-size: 11px; color: var(--color-text-secondary); margin-left: 8px;">[${escapeHtml(r.period || 'weekly')}]</span>
            </div>
            <div class="detail-section">
                <div class="ds-title">基础信息</div>
                <p>项目: <b>${escapeHtml(r.project_name || ('#' + r.project_id))}</b>
                    ${r.module_name ? ` &nbsp;|&nbsp; 模块: <b>${escapeHtml(r.module_name)}</b>` : ''}
                    ${r.group_name ? ` &nbsp;|&nbsp; Group: <b>${escapeHtml(r.group_name)}</b>` : ''}
                    ${r.subsystem ? ` &nbsp;|&nbsp; Subsystem: <b>${escapeHtml(r.subsystem)}</b>` : ''}
                </p>
                <p>创建人: ${escapeHtml(r.created_by_name || r.leader_name || r.manager_name || '?')}
                    &nbsp;|&nbsp; 创建: ${fmtTime(r.created_at)}
                    ${r.submitted_at ? `&nbsp;|&nbsp; 提交: ${fmtTime(r.submitted_at)}` : ''}
                    ${r.reviewed_by_name ? `&nbsp;|&nbsp; 审核: ${escapeHtml(r.reviewed_by_name)} @ ${fmtTime(r.reviewed_at)}` : ''}
                </p>
                ${r.review_comment ? `<p>审核评语: <i style="color:var(--color-text-secondary);">${escapeHtml(r.review_comment)}</i></p>` : ''}
            </div>
            ${r.summary ? `<div class="detail-section"><div class="ds-title">摘要</div><p>${escapeHtml(r.summary)}</p></div>` : ''}
            ${kpis.length ? `<div class="detail-section"><div class="ds-title">关键指标对比</div>${renderKeyMetricsTable(kpis)}</div>` : ''}
            <div class="detail-section"><div class="ds-title">关键发现</div>${findingsHtml}</div>
            <div class="detail-section"><div class="ds-title">待决策项</div>${decisionsHtml}</div>
            <div class="detail-section"><div class="ds-title">后续计划</div>${nextStepsHtml}</div>
            <div class="detail-section"><div class="ds-title">风险 / 行动</div>${risksHtml}</div>
            ${tileIds.length ? `<div class="detail-section"><div class="ds-title">关联 Tile Reviews (${tileIds.length})</div><p>${tileIds.map(id => `<a href="javascript:Review.viewDetail('tile', ${id})" style="color:var(--color-primary); margin-right: 6px;">#${id}</a>`).join('')}</p></div>` : ''}
            ${grpIds.length ? `<div class="detail-section"><div class="ds-title">关联 Group Reviews (${grpIds.length})</div><p>${grpIds.map(id => `<a href="javascript:Review.viewDetail('group', ${id})" style="color:var(--color-primary); margin-right: 6px;">#${id}</a>`).join('')}</p></div>` : ''}
            <div class="detail-section">
                <div class="ds-title">状态流转</div>
                <ul class="timeline">
                    <li><span class="tl-time">${fmtTime(r.created_at)}</span>创建 (by ${escapeHtml(r.created_by_name || r.leader_name || r.manager_name || '?')})</li>
                    ${r.submitted_at ? `<li><span class="tl-time">${fmtTime(r.submitted_at)}</span>提交审核</li>` : ''}
                    ${r.reviewed_at ? `<li><span class="tl-time">${fmtTime(r.reviewed_at)}</span>${r.status === 'rejected' ? '驳回' : '通过'} (by ${escapeHtml(r.reviewed_by_name || '?')})${r.review_comment ? ' — ' + escapeHtml(r.review_comment) : ''}</li>` : ''}
                    ${r.frozen_at ? `<li><span class="tl-time">${fmtTime(r.frozen_at)}</span>已冻结为 Snapshot</li>` : ''}
                </ul>
            </div>
        `;
        $('#detailModal').classList.add('show');
    }

    // ==================== Snapshot 相关 ====================
    function openCreateSnapshotModal() {
        $('#modalTitle').textContent = '新建 Snapshot';
        const projOpts = OPTIONS.projects.map(p => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join('');
        $('#formBody').innerHTML = `
            <div class="form-row">
                <label>项目 *</label>
                <select id="formProject" onchange="Review.onFormProjectChange('snapshot')">
                    <option value="">-- 请选择 --</option>${projOpts}
                </select>
            </div>
            <div class="form-row">
                <label>基于 Subsystem Review (可选, 自动冻结)</label>
                <select id="formSubsystemReview">
                    <option value="">-- 自定义快照 --</option>
                </select>
            </div>
            <div class="form-row">
                <label>名称 *</label>
                <input type="text" id="formName" placeholder="例: Tapeout v1.0 - TOP">
            </div>
            <div class="form-row">
                <label>类型</label>
                <select id="formType">
                    <option value="milestone">milestone - 里程碑</option>
                    <option value="tapeout">tapeout - 流片</option>
                    <option value="pre_release">pre_release - 预发布</option>
                    <option value="custom">custom - 自定义</option>
                </select>
            </div>
            <div class="form-row">
                <label>描述</label>
                <textarea id="formDesc"></textarea>
            </div>
        `;
        $('#formModal').classList.add('show');
    }

    async function submitSnapshotForm() {
        const body = {
            project_id: parseInt($('#formProject').value || '0', 10),
            subsystem_review_id: parseInt($('#formSubsystemReview').value || '0', 10) || null,
            name: $('#formName').value,
            snapshot_type: $('#formType').value,
            description: $('#formDesc').value,
        };
        if (!body.project_id) return alert('请选择项目');
        if (!body.name) return alert('请填写名称');
        const r = await fetch('/api/reviews/snapshot', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        const data = await r.json();
        if (!r.ok) return alert('创建失败: ' + (data.error || r.status));
        closeFormModal();
        loadSnapshots();
    }

    async function viewSnapshot(id) {
        const r = await fetch(`/api/reviews/snapshot/${id}`);
        const s = await r.json();
        const files = safeArr(s.files);
        const filesHtml = files.length
            ? `<div class="file-list">${files.map(f =>
                `<div class="file-row">
                    <span class="name">📄 ${escapeHtml(f.original_filename || f.filename)}</span>
                    <span style="color:var(--color-text-secondary); font-size:11px;">${escapeHtml(f.category || '')}</span>
                    <span style="color:var(--color-text-secondary); font-size:11px;">${(f.size || 0).toLocaleString()} B</span>
                    <a class="btn-sm" href="/api/reviews/file/${f.id}/download">下载</a>
                </div>`).join('')}</div>`
            : '<i style="color:var(--color-text-secondary); font-size:12px;">无附件</i>';
        $('#snapModalTitle').textContent = s.name;
        $('#snapModalBody').innerHTML = `
            <div class="detail-section">
                <div class="ds-title">基础信息</div>
                <p>类型: <b>${escapeHtml(s.snapshot_type || '')}</b> | 校验: ${s.verified ? '<span style="color:#2e7d32; font-weight:600;">✓ 完整</span>' : '<span style="color:#c62828; font-weight:600;">✗ 已篡改</span>'}</p>
                <p>sha256: <code style="font-size: 10px;">${escapeHtml(s.checksum || '')}</code></p>
                <p>记录数: <b>${s.record_count || 0}</b> &nbsp;|&nbsp; 关联 Subsystem Review: ${s.subsystem_review_id || '-'}</p>
                <p>创建者: ${escapeHtml(s.created_by_name || '?')} @ ${fmtTime(s.created_at)}</p>
                ${s.description ? `<p>${escapeHtml(s.description)}</p>` : ''}
            </div>
            <div class="detail-section">
                <div class="ds-title">附件 (${files.length})</div>
                ${filesHtml}
            </div>
            ${s.frozen_data ? `<div class="detail-section">
                <div class="ds-title">已冻结数据预览 (前 30 行)</div>
                <pre>${escapeHtml(JSON.stringify(s.frozen_data, null, 2).slice(0, 5000))}</pre>
            </div>` : ''}
        `;
        $('#snapModal').classList.add('show');
    }
    function closeSnapModal() { $('#snapModal').classList.remove('show'); }

    async function deleteSnapshot(id) {
        if (!confirm('确定删除 snapshot? 将一并删除附件磁盘文件')) return;
        const r = await fetch(`/api/reviews/snapshot/${id}`, { method: 'DELETE' });
        const data = await r.json();
        if (!r.ok) return alert('删除失败: ' + (data.error || r.status));
        loadSnapshots();
    }

    // ==================== 上传附件 ====================
    function openUploadModal(sid) {
        UPLOAD_SNAP_ID = sid;
        $('#uploadFile').value = '';
        $('#uploadDesc').value = '';
        $('#uploadModal').classList.add('show');
    }
    function closeUploadModal() { $('#uploadModal').classList.remove('show'); }
    async function doUpload() {
        const f = $('#uploadFile').files[0];
        if (!f) return alert('请选择文件');
        const fd = new FormData();
        fd.append('file', f);
        fd.append('category', $('#uploadCategory').value);
        fd.append('description', $('#uploadDesc').value);
        const r = await fetch(`/api/reviews/snapshot/${UPLOAD_SNAP_ID}/upload`, { method: 'POST', body: fd });
        const data = await r.json();
        if (!r.ok) return alert('上传失败: ' + (data.error || r.status));
        closeUploadModal();
        if (CURRENT_TAB === 'snapshot') loadSnapshots();
    }

    // ==================== 暴露 API ====================
    window.Review = {
        switchTab,
        loadActiveTab,
        viewDetail,
        closeDetailModal,
        openCreateModal,
        openEditModal,
        closeFormModal,
        openReviewActionModal,
        closeReviewActionModal,
        doReview,
        doAction,
        doDelete,
        onFormProjectChange,
        addTextRow,
        addDecRow,
        addKmRow,
        addRiskRow,
        rebuildListRow,
        submitForm,
        viewSnapshot,
        closeSnapModal,
        deleteSnapshot,
        openUploadModal,
        closeUploadModal,
        doUpload,
        // legacy aliases
        _legacy: {
            switchTab, loadActiveTab, viewDetail, closeDetailModal,
            openCreateModal, openEditModal, closeFormModal,
            openReviewActionModal, closeReviewActionModal,
            doReview, doAction, doDelete,
            onFormProjectChange, addTextRow, addDecRow, addKmRow, addRiskRow,
            rebuildListRow, submitForm, viewSnapshot, closeSnapModal,
            deleteSnapshot, openUploadModal, closeUploadModal, doUpload,
        }
    };

    // ==================== 启动 ====================
    (async function init() {
        // 兼容旧版 inline onclick 调用: 暴露部分函数到 window
        ['switchTab', 'loadActiveTab', 'openCreateModal', 'viewDetail', 'openEditModal',
         'closeDetailModal', 'closeFormModal', 'openReviewActionModal', 'closeReviewActionModal',
         'doReview', 'doAction', 'doDelete', 'onFormProjectChange', 'addTextRow', 'addDecRow',
         'addKmRow', 'addRiskRow', 'rebuildListRow', 'submitForm', 'viewSnapshot', 'closeSnapModal',
         'deleteSnapshot', 'openUploadModal', 'closeUploadModal', 'doUpload'].forEach(fn => {
            window[fn] = Review[fn] || Review._legacy[fn];
        });
        await loadOptions();
        loadActiveTab();
    })();
})();
