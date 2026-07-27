"""数据模型定义"""
import json
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


# =========================================================================
# 主题预设
# =========================================================================

DEFAULT_THEME = {
    # neon 主题: 深色霓虹科技风 (默认)
    'name': 'neon',
    'primary': '#00d4ff',
    'primary_gradient_end': '#7b2ff7',
    'background': '#0a0e1a',
    'surface': '#131829',
    'surface_hover': '#1a2138',
    'text': '#e6f1ff',
    'text_secondary': '#8b9bb4',
    'border': '#1f2a44',
    'navbar_text': 'rgba(230, 241, 255, 0.75)',
    'navbar_text_active': '#00d4ff',
}

THEME_PRESETS = {
    'classic': {
        'name': 'classic',
        'primary': '#1a237e',
        'primary_gradient_end': '#283593',
        'background': '#f0f2f5',
        'surface': '#ffffff',
        'surface_hover': '#fafafa',
        'text': '#333333',
        'text_secondary': '#666666',
        'border': '#e8e8e8',
        'navbar_text': 'rgba(255, 255, 255, 0.85)',
        'navbar_text_active': '#ffffff',
    },
    'neon': DEFAULT_THEME,
    'dark': {
        'name': 'dark',
        'primary': '#0d47a1',
        'primary_gradient_end': '#1565c0',
        'background': '#121212',
        'surface': '#1e1e1e',
        'surface_hover': '#2a2a2a',
        'text': '#e0e0e0',
        'text_secondary': '#9e9e9e',
        'border': '#333333',
        'navbar_text': 'rgba(255, 255, 255, 0.85)',
        'navbar_text_active': '#ffffff',
    },
    'green': {
        'name': 'green',
        'primary': '#1b5e20',
        'primary_gradient_end': '#2e7d32',
        'background': '#f1f8e9',
        'surface': '#ffffff',
        'surface_hover': '#f5f5f5',
        'text': '#333333',
        'text_secondary': '#666666',
        'border': '#e8e8e8',
        'navbar_text': 'rgba(255, 255, 255, 0.85)',
        'navbar_text_active': '#ffffff',
    },
    'purple': {
        'name': 'purple',
        'primary': '#4a148c',
        'primary_gradient_end': '#6a1b9a',
        'background': '#f3e5f5',
        'surface': '#ffffff',
        'surface_hover': '#f5f5f5',
        'text': '#333333',
        'text_secondary': '#666666',
        'border': '#e8e8e8',
        'navbar_text': 'rgba(255, 255, 255, 0.85)',
        'navbar_text_active': '#ffffff',
    },
    'orange': {
        'name': 'orange',
        'primary': '#bf360c',
        'primary_gradient_end': '#d84315',
        'background': '#fff3e0',
        'surface': '#ffffff',
        'surface_hover': '#f5f5f5',
        'text': '#333333',
        'text_secondary': '#666666',
        'border': '#e8e8e8',
        'navbar_text': 'rgba(255, 255, 255, 0.85)',
        'navbar_text_active': '#ffffff',
    },
}


class User(UserMixin, db.Model):
    """用户表"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='user')  # admin / user / release
    display_name = db.Column(db.String(120))
    # 用户自定义主题 (JSON), null 时使用默认主题
    theme = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    dashboards = db.relationship('UserDashboard', backref='user', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_release(self):
        """release 角色: 仅能查看已 release 的数据, 无管理权限"""
        return self.role == 'release'

    def get_theme(self):
        """获取用户主题, 未设置时返回默认主题"""
        if not self.theme:
            return dict(DEFAULT_THEME)
        try:
            data = json.loads(self.theme)
            if isinstance(data, str):
                data = json.loads(data)
            # 合并默认主题, 保证字段完整 (兼容历史数据 / 主题升级)
            merged = dict(DEFAULT_THEME)
            if isinstance(data, dict):
                merged.update(data)
            return merged
        except (json.JSONDecodeError, TypeError):
            return dict(DEFAULT_THEME)

    def set_theme(self, theme_dict):
        """设置用户主题"""
        self.theme = json.dumps(theme_dict, ensure_ascii=False)


class Project(db.Model):
    """项目表"""
    __tablename__ = 'projects'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # 项目状态: active(活跃) / locked(锁定,禁止写入) / archived(归档,只读且隐藏)
    status = db.Column(db.String(20), nullable=False, default='active', index=True)
    locked_at = db.Column(db.DateTime)         # 锁定时间
    locked_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # 锁定操作人
    lock_reason = db.Column(db.String(500))    # 锁定原因

    modules = db.relationship('Module', backref='project', lazy='dynamic', cascade='all, delete-orphan')
    locker = db.relationship('User', foreign_keys=[locked_by])

    @property
    def is_writable(self):
        """项目是否可写入 (active 状态才可写)"""
        return self.status == 'active'

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'status': self.status,
            'is_writable': self.is_writable,
            'locked_at': self.locked_at.isoformat() if self.locked_at else None,
            'locked_by': self.locked_by,
            'locked_by_name': self.locker.username if self.locker else None,
            'lock_reason': self.lock_reason,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Module(db.Model):
    """模块表"""
    __tablename__ = 'modules'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    records = db.relationship('QorRecord', backref='module', lazy='dynamic', cascade='all, delete-orphan')

    __table_args__ = (db.UniqueConstraint('project_id', 'name', name='uq_module_project_name'),)


class QorRecord(db.Model):
    """QoR 数据记录

    存储 Design Compiler 综合后的质量指标。
    核心字段覆盖标准 QoR 报告中的面积、时序、功耗、单元数量等。
    extra_fields 以 JSON 存储未映射到固定列的额外字段。
    """
    __tablename__ = 'qor_records'

    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey('modules.id'), nullable=False, index=True)

    # 版本标识：综合运行的版本号 / commit hash / 日期标签
    version = db.Column(db.String(200), default='v1')

    # ---- 面积 (Area, 单位: um²) ----
    area_total = db.Column(db.Float)
    area_combinational = db.Column(db.Float)
    area_sequential = db.Column(db.Float)
    area_black_box = db.Column(db.Float)
    area_macro = db.Column(db.Float)

    # ---- 时序 (Timing, 单位: ns) ----
    # Setup
    wns_setup = db.Column(db.Float)   # Worst Negative Slack
    tns_setup = db.Column(db.Float)   # Total Negative Slack
    nvp_setup = db.Column(db.Integer) # Number of Violating Paths
    # Hold
    wns_hold = db.Column(db.Float)
    tns_hold = db.Column(db.Float)
    nvp_hold = db.Column(db.Integer)

    # ---- 功耗 (Power, 单位: mW) ----
    power_internal = db.Column(db.Float)
    power_switching = db.Column(db.Float)
    power_leakage = db.Column(db.Float)
    power_total = db.Column(db.Float)

    # ---- 单元/网络统计 ----
    cell_count = db.Column(db.Integer)
    instance_count = db.Column(db.Integer)
    net_count = db.Column(db.Integer)
    sequential_cell_count = db.Column(db.Integer)

    # ---- 频率 ----
    target_frequency = db.Column(db.Float)  # MHz
    achieved_frequency = db.Column(db.Float)  # MHz

    # ---- 物理实现指标 ----
    mbb_ratio = db.Column(db.Float)           # Multi-Bit Flip-Flop 合并率 (%)
    clock_gating_ratio = db.Column(db.Float)  # 时钟门控覆盖率 (%)
    utilization = db.Column(db.Float)         # 布局利用率 (%)
    # 拥塞指数 (0-1 或 0-100): H=水平, V=垂直, B=Both(综合)
    # 旧字段 congestion 保留用于向后兼容, 新数据应使用 h/v/b 三字段
    congestion = db.Column(db.Float)          # 拥塞指数 (旧, 等同于 B)
    congestion_h = db.Column(db.Float)        # 水平拥塞指数 (Horizontal)
    congestion_v = db.Column(db.Float)        # 垂直拥塞指数 (Vertical)
    congestion_b = db.Column(db.Float)        # 综合拥塞指数 (Both)

    # ---- 额外字段 (JSON) ----
    extra_fields = db.Column(db.Text)  # JSON string

    # ---- 元数据 ----
    source_file = db.Column(db.String(500))
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ---- Release 标记 ----
    # True = 已对 release 角色账号可见 (对外发布); False/None = 仅内部可见
    is_released = db.Column(db.Boolean, nullable=False, default=False, index=True)
    released_at = db.Column(db.DateTime)
    released_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    def to_dict(self):
        """转换为字典"""
        import json
        extra = {}
        if self.extra_fields:
            try:
                extra = json.loads(self.extra_fields)
                # 兼容双重编码的旧数据（loads 后仍是字符串则再 loads 一次）
                if isinstance(extra, str):
                    extra = json.loads(extra)
            except (json.JSONDecodeError, TypeError):
                extra = {}
        result = {
            'id': self.id,
            'module_id': self.module_id,
            'module_name': self.module.name if self.module else None,
            'project_name': self.module.project.name if self.module and self.module.project else None,
            'version': self.version,
            'tag': self.version,  # tag 即 version，用于图表标签显示
            'comment': extra.get('comment', '') if isinstance(extra, dict) else '',
            'full_dir': extra.get('full_dir', '') if isinstance(extra, dict) else '',
            'area_total': self.area_total,
            'area_combinational': self.area_combinational,
            'area_sequential': self.area_sequential,
            'area_black_box': self.area_black_box,
            'area_macro': self.area_macro,
            'wns_setup': self.wns_setup,
            'tns_setup': self.tns_setup,
            'nvp_setup': self.nvp_setup,
            'wns_hold': self.wns_hold,
            'tns_hold': self.tns_hold,
            'nvp_hold': self.nvp_hold,
            'power_internal': self.power_internal,
            'power_switching': self.power_switching,
            'power_leakage': self.power_leakage,
            'power_total': self.power_total,
            'cell_count': self.cell_count,
            'instance_count': self.instance_count,
            'net_count': self.net_count,
            'sequential_cell_count': self.sequential_cell_count,
            'target_frequency': self.target_frequency,
            'achieved_frequency': self.achieved_frequency,
            'mbb_ratio': self.mbb_ratio,
            'clock_gating_ratio': self.clock_gating_ratio,
            'utilization': self.utilization,
            # 拥塞指数: H=水平 / V=垂直 / B=Both
            # 旧 congestion 字段保留; 若新字段为空则用旧 congestion 兜底 B (向后兼容)
            'congestion': self.congestion,
            'congestion_h': self.congestion_h,
            'congestion_v': self.congestion_v,
            'congestion_b': self.congestion_b if self.congestion_b is not None else self.congestion,
            'source_file': self.source_file,
            'recorded_at': self.recorded_at.isoformat() if self.recorded_at else None,
            'is_released': bool(self.is_released),
            'released_at': self.released_at.isoformat() if self.released_at else None,
            'extra_fields': extra,
        }
        return result


class ViolationPath(db.Model):
    """违例路径表

    存储每个 module/version 的具体违例路径信息。
    一个 (module, version) 可有多条违例路径，按 timing_group 分类。
    数据来源于 DC 报告的违例路径 CSV 文件（每个 timing group 一个 CSV）。
    """
    __tablename__ = 'violation_paths'

    id = db.Column(db.Integer, primary_key=True)
    qor_record_id = db.Column(db.Integer, db.ForeignKey('qor_records.id'), nullable=False, index=True)

    # timing group 名称（从文件名或 CSV 内容提取，如 SRAMCLK, CLK_CPU）
    timing_group = db.Column(db.String(200), index=True)

    # 路径端点
    startpoint = db.Column(db.String(500))
    endpoint = db.Column(db.String(500))

    # 时序指标
    slack = db.Column(db.Float)           # 违例 slack (ns)
    depth = db.Column(db.Integer)         # 路径深度
    pure_depth = db.Column(db.Integer)    # 纯逻辑深度
    cell_delay = db.Column(db.Float)      # 单元延迟 (ps 或 ns)
    net_delay = db.Column(db.Float)       # 网络延迟
    et_slack = db.Column(db.Float)        # ET slack
    st_slack = db.Column(db.Float)        # ST slack
    st_fanin = db.Column(db.Integer)      # ST fanin
    st_fanout = db.Column(db.Integer)     # ST fanout
    et_fanin = db.Column(db.Integer)      # ET fanin
    et_fanout = db.Column(db.Integer)     # ET fanout

    source_file = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    record = db.relationship('QorRecord', backref='violation_paths')

    def to_dict(self):
        return {
            'id': self.id,
            'qor_record_id': self.qor_record_id,
            'timing_group': self.timing_group,
            'startpoint': self.startpoint,
            'endpoint': self.endpoint,
            'slack': self.slack,
            'depth': self.depth,
            'pure_depth': self.pure_depth,
            'cell_delay': self.cell_delay,
            'net_delay': self.net_delay,
            'et_slack': self.et_slack,
            'st_slack': self.st_slack,
            'st_fanin': self.st_fanin,
            'st_fanout': self.st_fanout,
            'et_fanin': self.et_fanin,
            'et_fanout': self.et_fanout,
            'source_file': self.source_file,
        }


class RunNote(db.Model):
    """Run 备注/参数表

    存储每个 module/version/full_dir 的重要修改与参数（item + description 键值对）。
    关联到 QorRecord，继承其 is_released 可见性（release 账号只看已发布记录的备注）。
    数据来源于用户上传的 2~3 列 CSV（item, description[, full_dir]）。
    full_dir 用于区分同一 module+version 下不同目录的 run（例如多 corner / 多 sub-run）。
    """
    __tablename__ = 'run_notes'

    id = db.Column(db.Integer, primary_key=True)
    qor_record_id = db.Column(db.Integer, db.ForeignKey('qor_records.id'), nullable=False, index=True)
    item = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text)
    seq = db.Column(db.Integer, default=0)  # 排序序号
    source_file = db.Column(db.String(500))
    # full_dir: 关联到 QorRecord.extra_fields.full_dir, 用于区分同 module+version 下的不同 run 目录
    # 为空则表示该 module+version 下的通用备注（兼容老数据）
    full_dir = db.Column(db.String(1000), index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    record = db.relationship('QorRecord', backref=db.backref('notes', cascade='all, delete-orphan'))

    def to_dict(self):
        return {
            'id': self.id,
            'qor_record_id': self.qor_record_id,
            'item': self.item,
            'description': self.description,
            'seq': self.seq,
            'source_file': self.source_file,
            'full_dir': self.full_dir,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class UserDashboard(db.Model):
    """用户自定义 Dashboard 配置"""
    __tablename__ = 'user_dashboards'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    config = db.Column(db.Text, nullable=False)  # JSON: 包含选中的项目、模块、图表类型、指标等
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DashboardGroup(db.Model):
    """项目级 Dashboard Group 共享视图

    设计目标: 不同项目可以拥有同名但**内容独立**的 group 视图,
    group owner 与成员打开 dashboard 时**无需保存个人模板**即可看到
    该 group 共享的 config, 实现"团队默认视图"语义。

    与 UserDashboard 的区别:
      - UserDashboard: 单人私有, 只对当前 user 可见
      - DashboardGroup: 跨用户共享, owner 管理, 成员只读应用

    关键字段:
      - project_id: 所属项目; NULL = 全局 group(跨项目共享)
      - owner_id: 创建者, 可编辑/删除/邀请成员
      - member_ids: JSON 数组, 共享成员 user_id 列表
      - config: 同样的 JSON 结构 (与 user_dashboards.config 兼容)
      - shared_default: 成员登录时是否自动应用此 group 的 config
      - is_public: 项目内非成员是否可只读访问 (默认 False, 严格私有)
    """
    __tablename__ = 'dashboard_groups'
    __table_args__ = (
        db.UniqueConstraint('project_id', 'name', name='uq_dashboard_groups_project_name'),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    # 所属项目; NULL = 全局 group, 非 NULL = 项目专属 group
    # 配合 UniqueConstraint(project_id, name) 实现"不同项目同名 group 互不干扰"
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=True, index=True)
    # group owner (创建者)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    # 共享成员 user_id 列表 (JSON 数组); owner 自动视为成员
    member_ids = db.Column(db.Text, nullable=False, default='[]')
    # 共享 config (与 user_dashboards.config 同样的 JSON 结构)
    config = db.Column(db.Text, nullable=False, default='{}')
    # 成员登录时是否自动加载
    shared_default = db.Column(db.Boolean, nullable=False, default=False)
    # 是否对项目内所有用户只读可见
    is_public = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系: 关联到项目和 owner, 供 to_dict / 模板渲染使用
    project = db.relationship('Project', backref=db.backref('dashboard_groups', lazy='dynamic'),
                              foreign_keys=[project_id])
    owner = db.relationship('User', backref=db.backref('owned_dashboard_groups', lazy='dynamic'),
                            foreign_keys=[owner_id])

    def get_member_ids(self):
        """返回成员 user_id 列表 (含 owner)"""
        import json
        try:
            members = json.loads(self.member_ids) if self.member_ids else []
        except (json.JSONDecodeError, TypeError):
            members = []
        if self.owner_id not in members:
            members.insert(0, self.owner_id)
        return members

    def is_member(self, user_id):
        return int(user_id) in [int(x) for x in self.get_member_ids()]

    def is_visible_to(self, user, role):
        """当前 user/role 是否有权查看此 group"""
        # admin 看所有
        if role == 'admin':
            return True
        # owner / member 总可见
        if self.is_member(user.id):
            return True
        # release 角色: 只看公开 + 项目已发布
        if role == 'release':
            if not self.is_public:
                return False
            # 进一步要求: 此 group 关联的项目下有已发布数据
            from sqlalchemy import and_
            from models import QorRecord, Module
            if self.project_id is None:
                # 全局 group + 公开 + 至少有一条已发布记录
                return QorRecord.query.filter_by(is_released=True).first() is not None
            return QorRecord.query.join(Module).filter(
                Module.project_id == self.project_id,
                QorRecord.is_released == True  # noqa: E712
            ).first() is not None
        # user: 公开可见
        return self.is_public

    def can_edit(self, user, role):
        """是否有编辑权限: owner / admin"""
        if role == 'admin':
            return True
        return self.owner_id == user.id

    def to_dict(self, include_config=True):
        result = {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'project_id': self.project_id,
            'project_name': self.project.name if self.project else None,
            'owner_id': self.owner_id,
            'owner_name': self.owner.username if self.owner else None,
            'member_ids': self.get_member_ids(),
            'is_public': bool(self.is_public),
            'shared_default': bool(self.shared_default),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_config:
            import json
            try:
                result['config'] = json.loads(self.config) if self.config else {}
            except (json.JSONDecodeError, TypeError):
                result['config'] = {}
        return result


# =========================================================================
# API Key (自动化集成认证)
# =========================================================================

class ApiKey(db.Model):
    """API Key - 用于 DC 流程等自动化场景的程序化认证

    明文 key 仅在创建时返回一次, 数据库只存 sha256 哈希。
    key 格式: qor_<32位hex>, 前缀 prefix (前12位) 用于展示和识别。
    """
    __tablename__ = 'api_keys'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    key_hash = db.Column(db.String(128), unique=True, nullable=False, index=True)  # sha256 hex
    prefix = db.Column(db.String(16), nullable=False, index=True)  # 展示用前缀
    name = db.Column(db.String(120), nullable=False)  # 用途说明
    scopes = db.Column(db.String(200), default='read')  # 逗号分隔: read,upload,admin
    last_used_at = db.Column(db.DateTime)
    expires_at = db.Column(db.DateTime)  # null=永不过期
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    revoked = db.Column(db.Boolean, default=False)

    user = db.relationship('User', backref='api_keys')

    @staticmethod
    def generate_key():
        """生成新 API key 明文 (qor_xxx格式)"""
        import secrets
        return 'qor_' + secrets.token_hex(16)

    @staticmethod
    def hash_key(plaintext):
        import hashlib
        return hashlib.sha256(plaintext.encode('utf-8')).hexdigest()

    def has_scope(self, scope):
        if not self.scopes:
            return False
        return scope in [s.strip() for s in self.scopes.split(',')]

    @property
    def is_expired(self):
        return self.expires_at is not None and self.expires_at < datetime.utcnow()

    @property
    def is_valid(self):
        return not self.revoked and not self.is_expired

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'prefix': self.prefix,
            'scopes': self.scopes,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'revoked': self.revoked,
        }


# =========================================================================
# 项目级权限 (多用户协作)
# =========================================================================

class ProjectMember(db.Model):
    """项目成员 - 控制用户对项目的访问权限

    role:
      owner  - 项目所有者, 可管理成员、删除项目
      editor - 可上传/修改/删除数据
      viewer - 只读
    """
    __tablename__ = 'project_members'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False, default='viewer')  # owner/editor/viewer
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    project = db.relationship('Project', backref='members')
    user = db.relationship('User', backref='project_memberships')

    __table_args__ = (db.UniqueConstraint('project_id', 'user_id', name='uq_project_member'),)

    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'user_id': self.user_id,
            'username': self.user.username if self.user else None,
            'display_name': self.user.display_name if self.user else None,
            'role': self.role,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class DataLock(db.Model):
    """数据锁 - 防止多人同时编辑同一资源

    resource_type: project / module / record
    锁有过期时间 (默认30分钟), 过期自动释放。
    """
    __tablename__ = 'data_locks'

    id = db.Column(db.Integer, primary_key=True)
    resource_type = db.Column(db.String(20), nullable=False, index=True)  # project/module/record
    resource_id = db.Column(db.Integer, nullable=False, index=True)
    locked_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    locked_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)  # 强制要求过期时间
    reason = db.Column(db.String(500))

    user = db.relationship('User', backref='locks')

    __table_args__ = (db.UniqueConstraint('resource_type', 'resource_id', name='uq_resource_lock'),)

    @property
    def is_expired(self):
        return self.expires_at < datetime.utcnow()

    def to_dict(self):
        return {
            'id': self.id,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'locked_by': self.locked_by,
            'locked_by_name': self.user.username if self.user else None,
            'locked_at': self.locked_at.isoformat() if self.locked_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'reason': self.reason,
            'is_expired': self.is_expired,
        }


# =========================================================================
# 趋势预警
# =========================================================================

class AlertRule(db.Model):
    """告警规则 - 监控指标趋势, WNS 恶化等

    direction:
      worsen     - 指标变差 (如 wns 从 -0.1 变 -0.5)
      improve    - 指标变好
      threshold  - 超过绝对阈值
    metric: wns_setup / wns_hold / area_total / tns_setup / ...
    window_size: 对比最近 N 个版本 (默认1, 即与上一版本比)
    sensitivity: 变化幅度阈值 (百分比, 如 0.2 = 变化超过20%)
    """
    __tablename__ = 'alert_rules'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)
    module_id = db.Column(db.Integer, db.ForeignKey('modules.id'), nullable=True)  # null=全部模块
    metric = db.Column(db.String(50), nullable=False)  # wns_setup, area_total...
    direction = db.Column(db.String(20), nullable=False, default='worsen')
    threshold = db.Column(db.Float)  # 绝对阈值 (direction=threshold 时使用)
    window_size = db.Column(db.Integer, default=1)
    sensitivity = db.Column(db.Float, default=0.2)  # 20% 变化
    enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    events = db.relationship('AlertEvent', backref='rule', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'module_id': self.module_id,
            'metric': self.metric,
            'direction': self.direction,
            'threshold': self.threshold,
            'window_size': self.window_size,
            'sensitivity': self.sensitivity,
            'enabled': self.enabled,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class AlertEvent(db.Model):
    """告警事件 - 规则触发记录"""
    __tablename__ = 'alert_events'

    id = db.Column(db.Integer, primary_key=True)
    rule_id = db.Column(db.Integer, db.ForeignKey('alert_rules.id'), nullable=False, index=True)
    qor_record_id = db.Column(db.Integer, db.ForeignKey('qor_records.id'), nullable=True)
    module_id = db.Column(db.Integer, db.ForeignKey('modules.id'), nullable=True)
    old_value = db.Column(db.Float)
    new_value = db.Column(db.Float)
    delta = db.Column(db.Float)
    message = db.Column(db.Text)
    severity = db.Column(db.String(20), default='warning')  # info/warning/critical
    triggered_at = db.Column(db.DateTime, default=datetime.utcnow)
    acknowledged_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    acknowledged_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'rule_id': self.rule_id,
            'qor_record_id': self.qor_record_id,
            'module_id': self.module_id,
            'old_value': self.old_value,
            'new_value': self.new_value,
            'delta': self.delta,
            'message': self.message,
            'severity': self.severity,
            'triggered_at': self.triggered_at.isoformat() if self.triggered_at else None,
            'acknowledged_by': self.acknowledged_by,
            'acknowledged_at': self.acknowledged_at.isoformat() if self.acknowledged_at else None,
        }


# =========================================================================
# 数据快照与回滚
# =========================================================================

class DataSnapshot(db.Model):
    """数据快照 - 关键节点的不可变数据备份

    用于 tapeout、里程碑等关键节点保存项目数据的完整快照。
    快照存储为 JSON, 包含当时所有模块/记录的完整数据。
    创建后不可修改 (immutable), 只能删除整个快照。
    """
    __tablename__ = 'data_snapshots'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('projects.id'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)           # 快照名称 (如 "Tapeout v2.0")
    description = db.Column(db.Text)
    snapshot_type = db.Column(db.String(20), default='milestone')  # milestone / tapeout / pre_release / custom
    # 快照数据: JSON, 包含 [{module_name, version, ...所有字段}, ...]
    data = db.Column(db.Text, nullable=False)
    record_count = db.Column(db.Integer, default=0)            # 快照中的记录数
    checksum = db.Column(db.String(64), nullable=False)        # sha256 校验和, 防篡改
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    project = db.relationship('Project', backref='snapshots')
    creator = db.relationship('User', backref='snapshots')

    @staticmethod
    def compute_checksum(data_str):
        """计算数据的 SHA256 校验和"""
        import hashlib
        return hashlib.sha256(data_str.encode('utf-8')).hexdigest()

    def verify_integrity(self):
        """校验快照数据完整性 (checksum 是否匹配)"""
        return self.checksum == self.compute_checksum(self.data)

    def to_dict(self, include_data=False):
        import json
        result = {
            'id': self.id,
            'project_id': self.project_id,
            'name': self.name,
            'description': self.description,
            'snapshot_type': self.snapshot_type,
            'record_count': self.record_count,
            'checksum': self.prefix_checksum,
            'verified': self.verify_integrity(),
            'created_by': self.created_by,
            'created_by_name': self.creator.username if self.creator else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        if include_data:
            try:
                result['data'] = json.loads(self.data) if self.data else []
            except (json.JSONDecodeError, TypeError):
                result['data'] = []
        return result

    @property
    def prefix_checksum(self):
        """校验和前12位用于展示"""
        return self.checksum[:12] if self.checksum else None


# =========================================================================
# 备份记录
# =========================================================================

class BackupRecord(db.Model):
    """备份记录 - 记录每次自动/手动备份的元信息

    与文件系统中的备份文件配合, 记录备份时间、大小、校验和。
    """
    __tablename__ = 'backup_records'

    id = db.Column(db.Integer, primary_key=True)
    backup_type = db.Column(db.String(20), default='auto')  # auto / manual / pre_migration
    file_path = db.Column(db.String(500), nullable=False)   # 备份文件路径
    file_size = db.Column(db.Integer)                       # 文件大小 (bytes)
    checksum = db.Column(db.String(64))                     # 文件 sha256
    record_count = db.Column(db.Integer)                    # 当时 DB 中的记录数
    status = db.Column(db.String(20), default='ok')         # ok / failed / deleted
    message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'backup_type': self.backup_type,
            'file_path': self.file_path,
            'file_size': self.file_size,
            'file_size_mb': round(self.file_size / 1024 / 1024, 2) if self.file_size else 0,
            'checksum': self.checksum[:12] if self.checksum else None,
            'record_count': self.record_count,
            'status': self.status,
            'message': self.message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
