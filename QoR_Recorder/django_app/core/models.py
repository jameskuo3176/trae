"""Django ORM 数据模型

与 Flask SQLAlchemy 版本 models.py 保持一致, 转换为 Django ORM。

数据库分布:
  主库 (default): User, Project, ProjectMember, DataLock, ApiKey, 
                  BackupRecord, UserDashboard
  项目库 (project_<id>): Module, QorRecord, ViolationPath, RunNote,
                         DashboardGroup, AlertRule, AlertEvent, 
                         DataSnapshot, TileReview, GroupReview, 
                         SubsystemReview, ReviewSnapshot, ReviewFile
"""
import hashlib
import hmac
import json
import os
import secrets
import re
import unicodedata
from datetime import datetime

from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


# =========================================================================
# 主题预设
# =========================================================================

DEFAULT_THEME = {
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
}

THEME_PRESETS = {
    'classic': DEFAULT_THEME,
    'neon': {
        'name': 'neon',
        'primary': '#00d4ff', 'primary_gradient_end': '#7b2ff7',
        'background': '#0a0e1a', 'surface': '#131829',
        'surface_hover': '#1a2138', 'text': '#e6f1ff',
        'text_secondary': '#8b9bb4', 'border': '#1f2a44',
        'navbar_text': 'rgba(230, 241, 255, 0.75)',
        'navbar_text_active': '#00d4ff',
    },
    'dark': {
        'name': 'dark',
        'primary': '#0d47a1', 'primary_gradient_end': '#1565c0',
        'background': '#121212', 'surface': '#1e1e1e',
        'surface_hover': '#2a2a2a', 'text': '#e0e0e0',
        'text_secondary': '#9e9e9e', 'border': '#333333',
        'navbar_text': 'rgba(255, 255, 255, 0.85)',
        'navbar_text_active': '#ffffff',
    },
    'green': {
        'name': 'green',
        'primary': '#1b5e20', 'primary_gradient_end': '#2e7d32',
        'background': '#f1f8e9', 'surface': '#ffffff',
        'surface_hover': '#f5f5f5', 'text': '#333333',
        'text_secondary': '#666666', 'border': '#e8e8e8',
        'navbar_text': 'rgba(255, 255, 255, 0.85)',
        'navbar_text_active': '#ffffff',
    },
    'purple': {
        'name': 'purple',
        'primary': '#4a148c', 'primary_gradient_end': '#6a1b9a',
        'background': '#f3e5f5', 'surface': '#ffffff',
        'surface_hover': '#f5f5f5', 'text': '#333333',
        'text_secondary': '#666666', 'border': '#e8e8e8',
        'navbar_text': 'rgba(255, 255, 255, 0.85)',
        'navbar_text_active': '#ffffff',
    },
    'orange': {
        'name': 'orange',
        'primary': '#bf360c', 'primary_gradient_end': '#d84315',
        'background': '#fff3e0', 'surface': '#ffffff',
        'surface_hover': '#f5f5f5', 'text': '#333333',
        'text_secondary': '#666666', 'border': '#e8e8e8',
        'navbar_text': 'rgba(255, 255, 255, 0.85)',
        'navbar_text_active': '#ffffff',
    },
}


# =========================================================================
# Review 状态机常量
# =========================================================================

REVIEW_STATUS_DRAFT = 'draft'
REVIEW_STATUS_SUBMITTED = 'submitted'
REVIEW_STATUS_APPROVED = 'approved'
REVIEW_STATUS_REJECTED = 'rejected'
REVIEW_STATUS_FROZEN = 'frozen'

REVIEW_STATUS_CHOICES = [
    (REVIEW_STATUS_DRAFT, '草稿'),
    (REVIEW_STATUS_SUBMITTED, '已提交'),
    (REVIEW_STATUS_APPROVED, '已批准'),
    (REVIEW_STATUS_REJECTED, '已驳回'),
    (REVIEW_STATUS_FROZEN, '已冻结'),
]


# =========================================================================
# 主库模型
# =========================================================================

class User(AbstractUser):
    """用户表 - v5.0 角色模型

    admin  : 系统管理员, 所有权限
    owner  : 数据全权用户, 可上传/管理自己+协作者模块数据
    viewer : 只读用户, 仅能查看已发布数据
    """
    ROLE_ADMIN = 'admin'
    ROLE_OWNER = 'owner'
    ROLE_VIEWER = 'viewer'

    ROLE_CHOICES = [
        (ROLE_ADMIN, '管理员'),
        (ROLE_OWNER, '数据全权用户'),
        (ROLE_VIEWER, '只读用户'),
    ]

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_OWNER)
    display_name = models.CharField(max_length=120, blank=True, default='')
    theme = models.TextField(null=True, blank=True)
    must_change_password = models.BooleanField(default=False)
    password_changed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'users'
        verbose_name = '用户'
        verbose_name_plural = '用户'

    def check_password(self, raw_password):
        """验证密码, 兼容 Flask scrypt 格式

        Django 的 AbstractUser.check_password 会调用 password hashers,
        但 Flask scrypt 格式 ('flask_scrypt$...') 不在 Django 内置 hasher 列表中。
        这里重写以支持:
          1. 标准 Django 格式 (由 set_password 生成)
          2. Flask scrypt 格式 (旧数据迁移过来的)
        """
        encoded = self.password
        if not encoded:
            return False

        # 标准 Django 格式: 交给父类处理
        if not encoded.startswith('flask_scrypt$'):
            return super().check_password(raw_password)

        # Flask scrypt 格式: flask_scrypt$32768:8:1$salt$hash
        try:
            rest = encoded[len('flask_scrypt$'):]
            # 格式: 32768:8:1$salt$hash
            if '$' not in rest:
                return False
            params, salt, stored_hash = rest.split('$', 2)
            n, r, p = params.split(':')
            n, r, p = int(n), int(r), int(p)

            # 使用 hashlib.scrypt (Python 3.6+)
            derived = hashlib.scrypt(
                raw_password.encode('utf-8'),
                salt=salt.encode('utf-8'),
                n=n, r=r, p=p,
                maxmem=256 * 1024 * 1024,  # 256MB
            )
            return hmac.compare_digest(derived.hex(), stored_hash)
        except Exception:
            return False

    @property
    def is_admin(self):
        return self.role == self.ROLE_ADMIN

    @property
    def is_owner(self):
        return self.role == self.ROLE_OWNER

    @property
    def is_viewer(self):
        return self.role == self.ROLE_VIEWER

    @property
    def is_release(self):
        """兼容旧 release 角色"""
        return self.role in (self.ROLE_OWNER, 'release')

    def get_theme(self):
        if not self.theme:
            return dict(DEFAULT_THEME)
        try:
            data = json.loads(self.theme)
            if isinstance(data, str):
                data = json.loads(data)
            merged = dict(DEFAULT_THEME)
            if isinstance(data, dict):
                merged.update(data)
            return merged
        except (json.JSONDecodeError, TypeError):
            return dict(DEFAULT_THEME)

    def set_theme(self, theme_dict):
        self.theme = json.dumps(theme_dict, ensure_ascii=False)

    def __str__(self):
        return self.display_name or self.username


class Project(models.Model):
    """项目表"""
    STATUS_CHOICES = [
        ('active', '活跃'),
        ('locked', '锁定'),
        ('archived', '归档'),
        ('hidden', '隐藏'),
    ]

    name = models.CharField(max_length=200, db_index=True)
    description = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=20, default='active', db_index=True, choices=STATUS_CHOICES)
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='locked_projects', db_column='locked_by')
    lock_reason = models.CharField(max_length=500, blank=True, default='')
    hidden_at = models.DateTimeField(null=True, blank=True)
    hidden_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='hidden_projects', db_column='hidden_by')
    db_path = models.CharField(max_length=500, blank=True, default='')

    class Meta:
        db_table = 'projects'
        verbose_name = '项目'
        verbose_name_plural = '项目'

    @property
    def is_writable(self):
        return self.status == 'active'

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'status': self.status,
            'is_writable': self.is_writable,
            'locked_at': self.locked_at.isoformat() if self.locked_at else None,
            'locked_by': self.locked_by_id,
            'locked_by_name': self.locked_by.username if self.locked_by else None,
            'lock_reason': self.lock_reason,
            'hidden_at': self.hidden_at.isoformat() if self.hidden_at else None,
            'hidden_by': self.hidden_by_id,
            'db_path': self.db_path,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __str__(self):
        return self.name


class ProjectMember(models.Model):
    """项目成员"""
    ROLE_CHOICES = [
        ('owner', '所有者'),
        ('editor', '编辑者'),
        ('viewer', '只读'),
    ]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='project_memberships')
    role = models.CharField(max_length=20, default='viewer', choices=ROLE_CHOICES)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'project_members'
        unique_together = [('project', 'user')]
        verbose_name = '项目成员'
        verbose_name_plural = '项目成员'

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


def normalize_module_name(name):
    """Canonical module key shared by every project."""
    if not isinstance(name, str):
        raise ValueError('module name must be a string')
    normalized = unicodedata.normalize('NFKC', name).strip().casefold()
    normalized = re.sub(r'\s+', ' ', normalized)
    if not normalized:
        raise ValueError('module name must not be empty')
    return normalized


class GlobalModule(models.Model):
    """Canonical module metadata in the default relational database.

    The legacy ``Module`` model remains in project databases until all local
    foreign keys have been migrated. New APIs expose this model's ID.
    """
    name = models.CharField(max_length=200)
    normalized_name = models.CharField(max_length=200, unique=True, db_index=True)
    description = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'global_modules'
        ordering = ('normalized_name',)

    def save(self, *args, **kwargs):
        self.name = unicodedata.normalize('NFKC', self.name).strip()
        self.normalized_name = normalize_module_name(self.name)
        self.updated_at = timezone.now()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ProjectModule(models.Model):
    """Explicit many-to-many association between projects and global modules."""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='module_links')
    module = models.ForeignKey(GlobalModule, on_delete=models.CASCADE, related_name='project_links')
    owner_id = models.IntegerField(null=True, blank=True, db_index=True)
    collaborators = models.TextField(default='[]')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'project_modules'
        constraints = [
            models.UniqueConstraint(fields=('project', 'module'), name='uq_project_global_module'),
        ]


class ReviewGroup(models.Model):
    """YAML-managed review group within one project."""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='review_groups')
    name = models.CharField(max_length=200)
    owner = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='owned_review_groups',
    )
    description = models.TextField(blank=True, default='')
    config_version = models.CharField(max_length=64, blank=True, default='')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'review_groups'
        constraints = [
            models.UniqueConstraint(fields=('project', 'name'), name='uq_project_review_group'),
        ]


class ReviewGroupModule(models.Model):
    """Assign a project/global module pair to exactly one review group."""
    group = models.ForeignKey(ReviewGroup, on_delete=models.CASCADE, related_name='module_links')
    project_module = models.OneToOneField(
        ProjectModule, on_delete=models.CASCADE, related_name='review_group_link',
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'review_group_modules'


class ReviewHierarchySyncState(models.Model):
    """Singleton audit record for the last applied hierarchy configuration."""
    singleton = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    config_path = models.TextField(blank=True, default='')
    config_version = models.CharField(max_length=64, blank=True, default='')
    config_checksum = models.CharField(max_length=64, blank=True, default='')
    applied_at = models.DateTimeField(null=True, blank=True)
    summary = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'review_hierarchy_sync_state'


class WeeklyRunSelection(models.Model):
    """Central identity record for a project-scoped official weekly run.

    This intentionally remains in the main database: its project/global-module/
    user relationships are all central identities. The selected project-local
    QoR row is represented only by ``record_id``; no cross-database FK exists.
    """
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='weekly_run_selections')
    module = models.ForeignKey(
        GlobalModule, on_delete=models.CASCADE, related_name='weekly_run_selections',
    )
    week_start = models.DateField(db_index=True)
    record_id = models.CharField(max_length=64)
    source = models.CharField(max_length=40, default='weekly_release')
    selected_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='weekly_run_selections',
    )
    explicit = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'weekly_run_selections'
        constraints = [
            models.UniqueConstraint(
                fields=('project', 'module', 'week_start'),
                name='uq_project_module_weekly_run',
            ),
        ]


class LegacyModuleMapping(models.Model):
    """Rollback-safe mapping; no legacy project row is modified automatically."""
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='legacy_module_mappings')
    legacy_module_id = models.BigIntegerField()
    module = models.ForeignKey(GlobalModule, on_delete=models.CASCADE, related_name='legacy_mappings')
    legacy_name = models.CharField(max_length=200)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'legacy_module_mappings'
        constraints = [
            models.UniqueConstraint(
                fields=('project', 'legacy_module_id'), name='uq_project_legacy_module'
            ),
        ]


class DataLock(models.Model):
    """数据锁"""
    resource_type = models.CharField(max_length=20, db_index=True)
    resource_id = models.IntegerField(db_index=True)
    locked_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='locks', db_column='locked_by')
    locked_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    reason = models.CharField(max_length=500, blank=True, default='')

    class Meta:
        db_table = 'data_locks'
        unique_together = [('resource_type', 'resource_id')]
        verbose_name = '数据锁'
        verbose_name_plural = '数据锁'

    @property
    def is_expired(self):
        return self.expires_at < timezone.now()

    def to_dict(self):
        return {
            'id': self.id,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'locked_by': self.locked_by_id,
            'locked_by_name': self.locked_by.username if self.locked_by else None,
            'locked_at': self.locked_at.isoformat() if self.locked_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'reason': self.reason,
            'is_expired': self.is_expired,
        }


class ApiKey(models.Model):
    """API Key"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='api_keys')
    key_hash = models.CharField(max_length=128, unique=True, db_index=True)
    prefix = models.CharField(max_length=16, db_index=True)
    name = models.CharField(max_length=120)
    scopes = models.CharField(max_length=200, default='read')
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    revoked = models.BooleanField(default=False)

    class Meta:
        db_table = 'api_keys'
        verbose_name = 'API Key'
        verbose_name_plural = 'API Keys'

    @staticmethod
    def generate_key():
        return 'qor_' + secrets.token_hex(16)

    @staticmethod
    def hash_key(plaintext):
        return hashlib.sha256(plaintext.encode('utf-8')).hexdigest()

    def has_scope(self, scope):
        if not self.scopes:
            return False
        return scope in [s.strip() for s in self.scopes.split(',')]

    @property
    def is_expired(self):
        return self.expires_at is not None and self.expires_at < timezone.now()

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


class BackupRecord(models.Model):
    """备份记录"""
    backup_type = models.CharField(max_length=20, default='auto')
    file_path = models.CharField(max_length=500)
    file_size = models.IntegerField(null=True, blank=True)
    checksum = models.CharField(max_length=64, blank=True, default='')
    record_count = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, default='ok')
    message = models.TextField(blank=True, default='')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='backups')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'backup_records'
        verbose_name = '备份记录'
        verbose_name_plural = '备份记录'

    def to_dict(self):
        payload = {
            'id': self.id,
            'backup_type': self.backup_type,
            'file_path': self.file_path,
            'file_size': self.file_size,
            'file_size_mb': round(self.file_size / 1024 / 1024, 2) if self.file_size else 0,
            'checksum': self.checksum[:12] if self.checksum else None,
            'checksum_full': self.checksum or None,
            'record_count': self.record_count,
            'status': self.status,
            'message': self.message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'restore_command': (
                f'python manage.py restore_backup "{self.file_path}" --verify'
            ),
            'restore_apply_command': (
                f'python manage.py restore_backup "{self.file_path}" --verify --apply'
            ),
            'manifest': None,
            'verification_status': 'unknown',
        }
        if self.file_path and os.path.exists(self.file_path):
            from django_app.services.backup_service import read_backup_manifest_summary
            payload['manifest'] = read_backup_manifest_summary(self.file_path)
            payload['verification_status'] = 'present'
        elif self.file_path:
            payload['verification_status'] = 'missing'
        return payload


class UserDashboard(models.Model):
    """用户自定义 Dashboard 配置"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='dashboards')
    name = models.CharField(max_length=200)
    config = models.TextField()
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'user_dashboards'
        verbose_name = '用户 Dashboard'
        verbose_name_plural = '用户 Dashboards'


# =========================================================================
# 项目库模型 (通过数据库路由分配到 project_<id>)
# =========================================================================

class Module(models.Model):
    """模块表 - 项目库"""
    project_id = models.IntegerField(db_index=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')
    owner_id = models.IntegerField(null=True, blank=True, db_index=True)
    collaborators = models.TextField(default='[]')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'modules'
        unique_together = [('project_id', 'name')]
        verbose_name = '模块'
        verbose_name_plural = '模块'

    def get_collaborator_ids(self):
        if not self.collaborators:
            return []
        try:
            ids = json.loads(self.collaborators)
            if isinstance(ids, list):
                return [int(x) for x in ids if x is not None]
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        return []

    def set_collaborator_ids(self, ids):
        if ids is None:
            self.collaborators = '[]'
        else:
            cleaned = sorted(set(int(x) for x in ids if x is not None))
            self.collaborators = json.dumps(cleaned)

    def add_collaborator(self, user_id):
        ids = self.get_collaborator_ids()
        if int(user_id) not in ids:
            ids.append(int(user_id))
            self.set_collaborator_ids(ids)

    def remove_collaborator(self, user_id):
        ids = self.get_collaborator_ids()
        if int(user_id) in ids:
            ids.remove(int(user_id))
            self.set_collaborator_ids(ids)

    def can_be_managed_by(self, user):
        if user is None:
            return False
        if user.is_admin:
            return True
        if self.owner_id == user.id:
            return True
        if user.id in self.get_collaborator_ids():
            return True
        return False

    def __str__(self):
        return self.name


class QorRecord(models.Model):
    """QoR 数据记录 - 项目库"""
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name='records')
    version = models.CharField(max_length=200, default='v1')
    full_dir = models.CharField(max_length=500, db_index=True, blank=True, default='')

    # 面积
    area_total = models.FloatField(null=True, blank=True)
    area_combinational = models.FloatField(null=True, blank=True)
    area_sequential = models.FloatField(null=True, blank=True)
    area_black_box = models.FloatField(null=True, blank=True)
    area_macro = models.FloatField(null=True, blank=True)

    # 时序
    wns_setup = models.FloatField(null=True, blank=True)
    tns_setup = models.FloatField(null=True, blank=True)
    nvp_setup = models.IntegerField(null=True, blank=True)
    wns_hold = models.FloatField(null=True, blank=True)
    tns_hold = models.FloatField(null=True, blank=True)
    nvp_hold = models.IntegerField(null=True, blank=True)

    # 功耗
    power_internal = models.FloatField(null=True, blank=True)
    power_switching = models.FloatField(null=True, blank=True)
    power_leakage = models.FloatField(null=True, blank=True)
    power_total = models.FloatField(null=True, blank=True)

    # 单元/网络统计
    cell_count = models.IntegerField(null=True, blank=True)
    instance_count = models.IntegerField(null=True, blank=True)
    net_count = models.IntegerField(null=True, blank=True)
    sequential_cell_count = models.IntegerField(null=True, blank=True)
    ram_cell_count = models.IntegerField(null=True, blank=True)
    macro_cell_count = models.IntegerField(null=True, blank=True)

    # 频率
    target_frequency = models.FloatField(null=True, blank=True)
    achieved_frequency = models.FloatField(null=True, blank=True)

    # 物理实现指标
    mbb_ratio = models.FloatField(null=True, blank=True)
    clock_gating_ratio = models.FloatField(null=True, blank=True)
    utilization = models.FloatField(null=True, blank=True)
    congestion = models.FloatField(null=True, blank=True)
    congestion_h = models.FloatField(null=True, blank=True)
    congestion_v = models.FloatField(null=True, blank=True)
    congestion_b = models.FloatField(null=True, blank=True)

    # 寄存器数
    register_count = models.IntegerField(null=True, blank=True)

    # 原始 DC 报告
    raw_dc_report = models.TextField(null=True, blank=True)

    # 额外字段
    extra_fields = models.TextField(null=True, blank=True)

    # 元数据
    source_file = models.CharField(max_length=500, blank=True, default='')
    recorded_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(default=timezone.now)

    # Owner
    owner_id = models.IntegerField(null=True, blank=True, db_index=True)

    # Release
    is_released = models.BooleanField(default=False, db_index=True)
    released_at = models.DateTimeField(null=True, blank=True)
    released_by = models.IntegerField(null=True, blank=True)
    release_dir = models.CharField(max_length=500, db_index=True, blank=True, default='')
    version_description = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'qor_records'
        verbose_name = 'QoR 记录'
        verbose_name_plural = 'QoR 记录'

    def _compute_tag(self):
        if self.extra_fields:
            try:
                ef = self.extra_fields
                if isinstance(ef, str):
                    ef = json.loads(ef)
                if isinstance(ef, dict) and ef.get('tag'):
                    return ef['tag']
            except (json.JSONDecodeError, TypeError):
                pass
        if self.full_dir:
            fd = self.full_dir.rstrip('/').rstrip('\\')
            parts = fd.replace('\\', '/').split('/')
            last = parts[-1] if parts[-1] else (parts[-2] if len(parts) > 1 else fd)
            if last:
                return last
        return self.version or 'v1'

    def to_dict(self):
        extra = {}
        if self.extra_fields:
            try:
                extra = json.loads(self.extra_fields)
                if isinstance(extra, str):
                    extra = json.loads(extra)
            except (json.JSONDecodeError, TypeError):
                extra = {}
        full_dir = self.full_dir or (extra.get('full_dir', '') if isinstance(extra, dict) else '')
        release_dir_effective = self.release_dir or full_dir

        # 兼容 module 已被删除的孤立记录 (反向访问不存在对象会抛 DoesNotExist)
        try:
            module_name = self.module.name
            project_id = self.module.project_id
        except Module.DoesNotExist:
            module_name = None
            project_id = None

        result = {
            'id': self.id,
            'module_id': self.module_id,
            'module_name': module_name,
            'project_id': project_id,
            'version': self.version,
            'tag': self._compute_tag(),
            'comment': extra.get('comment', '') if isinstance(extra, dict) else '',
            'full_dir': full_dir,
            'release_dir': self.release_dir or '',
            'release_dir_effective': release_dir_effective,
            'version_description': self.version_description or '',
            'owner_id': self.owner_id,
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
            'ram_cell_count': self.ram_cell_count,
            'macro_cell_count': self.macro_cell_count,
            'register_count': self.register_count,
            'raw_dc_report': self.raw_dc_report,
            'target_frequency': self.target_frequency,
            'achieved_frequency': self.achieved_frequency,
            'mbb_ratio': self.mbb_ratio,
            'clock_gating_ratio': self.clock_gating_ratio,
            'utilization': self.utilization,
            'congestion': self.congestion,
            'congestion_h': self.congestion_h,
            'congestion_v': self.congestion_v,
            'congestion_b': self.congestion_b if self.congestion_b is not None else self.congestion,
            'source_file': self.source_file,
            'recorded_at': self.recorded_at.isoformat() if self.recorded_at else None,
            'is_released': bool(self.is_released),
            'released_at': self.released_at.isoformat() if self.released_at else None,
            'released_by': self.released_by,
            'extra_fields': extra,
        }
        return result

    def __str__(self):
        return f"QoR {self.id} - {self.module.name if self.module else '?'} - {self.version}"


class ViolationPath(models.Model):
    """违例路径表 - 项目库"""
    qor_record = models.ForeignKey(QorRecord, on_delete=models.CASCADE, related_name='violation_paths')
    timing_group = models.CharField(max_length=200, db_index=True, blank=True, default='')
    startpoint = models.CharField(max_length=500, blank=True, default='')
    endpoint = models.CharField(max_length=500, blank=True, default='')
    slack = models.FloatField(null=True, blank=True)
    depth = models.IntegerField(null=True, blank=True)
    pure_depth = models.IntegerField(null=True, blank=True)
    cell_delay = models.FloatField(null=True, blank=True)
    net_delay = models.FloatField(null=True, blank=True)
    et_slack = models.FloatField(null=True, blank=True)
    st_slack = models.FloatField(null=True, blank=True)
    st_fanin = models.IntegerField(null=True, blank=True)
    st_fanout = models.IntegerField(null=True, blank=True)
    et_fanin = models.IntegerField(null=True, blank=True)
    et_fanout = models.IntegerField(null=True, blank=True)
    source_file = models.CharField(max_length=500, blank=True, default='')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'violation_paths'
        verbose_name = '违例路径'
        verbose_name_plural = '违例路径'

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


class RunNote(models.Model):
    """Run 备注表 - 项目库"""
    qor_record = models.ForeignKey(QorRecord, on_delete=models.CASCADE, related_name='run_notes')
    item = models.CharField(max_length=500)
    description = models.TextField(blank=True, default='')
    seq = models.IntegerField(default=0)
    source_file = models.CharField(max_length=500, blank=True, default='')
    full_dir = models.CharField(max_length=1000, db_index=True, blank=True, default='')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'run_notes'
        verbose_name = 'Run 备注'
        verbose_name_plural = 'Run 备注'

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


class RecordAnnotation(models.Model):
    """One review annotation document per QoR record in its project database."""
    qor_record = models.OneToOneField(
        QorRecord, on_delete=models.CASCADE, related_name='annotation'
    )
    text = models.TextField(blank=True, default='')
    author_id = models.IntegerField()
    editor_id = models.IntegerField()
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'record_annotations'


class RecordAnnotationImage(models.Model):
    """Validated image bytes retained inside the project database."""
    annotation = models.ForeignKey(
        RecordAnnotation, on_delete=models.CASCADE, related_name='images'
    )
    filename = models.CharField(max_length=180)
    content_type = models.CharField(max_length=32)
    byte_size = models.PositiveIntegerField()
    checksum = models.CharField(max_length=64)
    content = models.BinaryField()
    uploaded_by = models.IntegerField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'record_annotation_images'
        ordering = ('id',)


class DashboardGroup(models.Model):
    """项目级 Dashboard Group 共享视图 - 项目库"""
    name = models.CharField(max_length=120)
    description = models.TextField(null=True, blank=True)
    project_id = models.IntegerField(null=True, blank=True, db_index=True)
    owner_id = models.IntegerField(db_index=True)
    member_ids = models.TextField(default='[]')
    config = models.TextField(default='{}')
    shared_default = models.BooleanField(default=False)
    is_public = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'dashboard_groups'
        unique_together = [('project_id', 'name')]
        verbose_name = 'Dashboard Group'
        verbose_name_plural = 'Dashboard Groups'

    def get_member_ids(self):
        try:
            members = json.loads(self.member_ids) if self.member_ids else []
        except (json.JSONDecodeError, TypeError):
            members = []
        if self.owner_id not in members:
            members.insert(0, self.owner_id)
        return members

    def is_member(self, user_id):
        return int(user_id) in [int(x) for x in self.get_member_ids()]

    def is_visible_to(self, user):
        if user.is_admin:
            return True
        if self.is_member(user.id):
            return True
        return self.is_public

    def can_edit(self, user):
        if user.is_admin:
            return True
        return self.owner_id == user.id

    def to_dict(self, include_config=True):
        result = {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'project_id': self.project_id,
            'owner_id': self.owner_id,
            'member_ids': self.get_member_ids(),
            'is_public': bool(self.is_public),
            'shared_default': bool(self.shared_default),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_config:
            try:
                result['config'] = json.loads(self.config) if self.config else {}
            except (json.JSONDecodeError, TypeError):
                result['config'] = {}
        return result


class AlertRule(models.Model):
    """告警规则 - 项目库"""
    project_id = models.IntegerField(db_index=True)
    module_id = models.IntegerField(null=True, blank=True)
    metric = models.CharField(max_length=50)
    direction = models.CharField(max_length=20, default='worsen')
    threshold = models.FloatField(null=True, blank=True)
    window_size = models.IntegerField(default=1)
    sensitivity = models.FloatField(default=0.2)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'alert_rules'
        verbose_name = '告警规则'
        verbose_name_plural = '告警规则'

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


class AlertEvent(models.Model):
    """告警事件 - 项目库"""
    rule = models.ForeignKey(AlertRule, on_delete=models.CASCADE, related_name='events')
    qor_record_id = models.IntegerField(null=True, blank=True)
    module_id = models.IntegerField(null=True, blank=True)
    old_value = models.FloatField(null=True, blank=True)
    new_value = models.FloatField(null=True, blank=True)
    delta = models.FloatField(null=True, blank=True)
    message = models.TextField(blank=True, default='')
    severity = models.CharField(max_length=20, default='warning')
    triggered_at = models.DateTimeField(default=timezone.now)
    acknowledged_by = models.IntegerField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'alert_events'
        verbose_name = '告警事件'
        verbose_name_plural = '告警事件'

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


class DataSnapshot(models.Model):
    """数据快照 - 项目库"""
    project_id = models.IntegerField(db_index=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')
    snapshot_type = models.CharField(max_length=20, default='milestone')
    data = models.TextField()
    record_count = models.IntegerField(default=0)
    checksum = models.CharField(max_length=64)
    created_by = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'data_snapshots'
        verbose_name = '数据快照'
        verbose_name_plural = '数据快照'

    @staticmethod
    def compute_checksum(data_str):
        return hashlib.sha256(data_str.encode('utf-8')).hexdigest()

    def verify_integrity(self):
        return self.checksum == self.compute_checksum(self.data)

    @property
    def prefix_checksum(self):
        return self.checksum[:12] if self.checksum else None

    def to_dict(self, include_data=False):
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
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        if include_data:
            try:
                result['data'] = json.loads(self.data) if self.data else []
            except (json.JSONDecodeError, TypeError):
                result['data'] = []
        return result


# =========================================================================
# Review 流程模型
# =========================================================================

class TileReview(models.Model):
    """Tile 级 Review - 项目库"""
    project_id = models.IntegerField(db_index=True)
    module_id = models.IntegerField(db_index=True)
    record = models.ForeignKey(QorRecord, on_delete=models.SET_NULL, null=True, blank=True, related_name='tile_reviews')
    title = models.CharField(max_length=200)
    period = models.CharField(max_length=20, default='weekly')
    summary = models.TextField(blank=True, default='')
    metrics_snapshot = models.TextField(null=True, blank=True)
    risks = models.TextField(null=True, blank=True)
    verdict = models.CharField(max_length=20, null=True, blank=True)
    key_metrics = models.TextField(null=True, blank=True)
    findings = models.TextField(null=True, blank=True)
    decisions = models.TextField(null=True, blank=True)
    next_steps = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=20, default=REVIEW_STATUS_DRAFT, db_index=True, choices=REVIEW_STATUS_CHOICES)
    created_by = models.IntegerField()
    submitted_by = models.IntegerField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.IntegerField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_comment = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'tile_reviews'
        verbose_name = 'Tile Review'
        verbose_name_plural = 'Tile Reviews'

    def to_dict(self, include_detail=False, include_snapshot=True):
        result = {
            'id': self.id,
            'project_id': self.project_id,
            'module_id': self.module_id,
            'record_id': self.record_id,
            'title': self.title,
            'period': self.period,
            'summary': self.summary,
            'verdict': self.verdict,
            'key_metrics': json.loads(self.key_metrics) if self.key_metrics else [],
            'findings': json.loads(self.findings) if self.findings else [],
            'decisions': json.loads(self.decisions) if self.decisions else [],
            'next_steps': json.loads(self.next_steps) if self.next_steps else [],
            'status': self.status,
            'risks': json.loads(self.risks) if self.risks else [],
            'created_by': self.created_by,
            'submitted_by': self.submitted_by,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
            'reviewed_by': self.reviewed_by,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'review_comment': self.review_comment,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_snapshot and self.metrics_snapshot:
            try:
                result['metrics_snapshot'] = json.loads(self.metrics_snapshot)
            except (json.JSONDecodeError, TypeError):
                result['metrics_snapshot'] = None
        return result


class GroupReview(models.Model):
    """Group 级 Review - 项目库"""
    project_id = models.IntegerField(db_index=True)
    group_name = models.CharField(max_length=100, db_index=True)
    period = models.CharField(max_length=20, default='weekly')
    title = models.CharField(max_length=200)
    summary = models.TextField(blank=True, default='')
    tile_review_ids = models.TextField(null=True, blank=True)
    aggregate = models.TextField(null=True, blank=True)
    risks = models.TextField(null=True, blank=True)
    verdict = models.CharField(max_length=20, null=True, blank=True)
    key_metrics = models.TextField(null=True, blank=True)
    findings = models.TextField(null=True, blank=True)
    decisions = models.TextField(null=True, blank=True)
    next_steps = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=20, default=REVIEW_STATUS_DRAFT, db_index=True, choices=REVIEW_STATUS_CHOICES)
    leader_id = models.IntegerField()
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.IntegerField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_comment = models.TextField(null=True, blank=True)
    snapshot_id = models.IntegerField(null=True, blank=True, db_index=True)
    snapshot_checksum = models.CharField(max_length=64, blank=True, default='')
    snapshot_week_start = models.DateField(null=True, blank=True, db_index=True)
    snapshot_schema_version = models.PositiveSmallIntegerField(null=True, blank=True)
    snapshot_config_version = models.CharField(max_length=64, blank=True, default='')
    snapshot_data = models.TextField(null=True, blank=True)
    submission_count = models.PositiveIntegerField(default=0)
    resubmitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'group_reviews'
        verbose_name = 'Group Review'
        verbose_name_plural = 'Group Reviews'

    def to_dict(self, include_detail=False):
        result = {
            'id': self.id,
            'project_id': self.project_id,
            'group_name': self.group_name,
            'period': self.period,
            'title': self.title,
            'summary': self.summary,
            'verdict': self.verdict,
            'key_metrics': json.loads(self.key_metrics) if self.key_metrics else [],
            'findings': json.loads(self.findings) if self.findings else [],
            'decisions': json.loads(self.decisions) if self.decisions else [],
            'next_steps': json.loads(self.next_steps) if self.next_steps else [],
            'tile_review_ids': json.loads(self.tile_review_ids) if self.tile_review_ids else [],
            'risks': json.loads(self.risks) if self.risks else [],
            'status': self.status,
            'leader_id': self.leader_id,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
            'reviewed_by': self.reviewed_by,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'review_comment': self.review_comment,
            'submission_count': self.submission_count,
            'resubmitted_at': self.resubmitted_at.isoformat() if self.resubmitted_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'snapshot_provenance': self.snapshot_provenance(),
        }
        if self.aggregate:
            try:
                result['aggregate'] = json.loads(self.aggregate)
            except (json.JSONDecodeError, TypeError):
                result['aggregate'] = None
        return result

    def snapshot_provenance(self):
        if not self.snapshot_id:
            return {
                'binding': 'legacy_live_unbound',
                'label': 'Legacy / live-unbound',
                'verified': None,
            }
        copy_checksum = (
            hashlib.sha256(self.snapshot_data.encode('utf-8')).hexdigest()
            if self.snapshot_data else ''
        )
        return {
            'binding': 'frozen',
            'label': 'Frozen snapshot',
            'id': self.snapshot_id,
            'checksum': self.snapshot_checksum,
            'week_start': (
                self.snapshot_week_start.isoformat()
                if self.snapshot_week_start else None
            ),
            'schema_version': self.snapshot_schema_version,
            'config_version': self.snapshot_config_version,
            'copy_verified': bool(
                self.snapshot_data and copy_checksum == self.snapshot_checksum
            ),
        }


class SubsystemReview(models.Model):
    """Subsystem 级 Review - 项目库"""
    project_id = models.IntegerField(db_index=True)
    subsystem = models.CharField(max_length=100, db_index=True)
    period = models.CharField(max_length=20, default='weekly')
    title = models.CharField(max_length=200)
    summary = models.TextField(blank=True, default='')
    group_review_ids = models.TextField(null=True, blank=True)
    aggregate = models.TextField(null=True, blank=True)
    risks = models.TextField(null=True, blank=True)
    verdict = models.CharField(max_length=20, null=True, blank=True)
    key_metrics = models.TextField(null=True, blank=True)
    findings = models.TextField(null=True, blank=True)
    decisions = models.TextField(null=True, blank=True)
    next_steps = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=20, default=REVIEW_STATUS_DRAFT, db_index=True, choices=REVIEW_STATUS_CHOICES)
    manager_id = models.IntegerField()
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.IntegerField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_comment = models.TextField(null=True, blank=True)
    snapshot_id = models.IntegerField(null=True, blank=True, db_index=True)
    snapshot_checksum = models.CharField(max_length=64, blank=True, default='')
    snapshot_week_start = models.DateField(null=True, blank=True, db_index=True)
    snapshot_schema_version = models.PositiveSmallIntegerField(null=True, blank=True)
    snapshot_config_version = models.CharField(max_length=64, blank=True, default='')
    snapshot_data = models.TextField(null=True, blank=True)
    submission_count = models.PositiveIntegerField(default=0)
    resubmitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'subsystem_reviews'
        verbose_name = 'Subsystem Review'
        verbose_name_plural = 'Subsystem Reviews'

    def to_dict(self, include_detail=False):
        result = {
            'id': self.id,
            'project_id': self.project_id,
            'project_name': self.subsystem,
            'subsystem': self.subsystem,
            'period': self.period,
            'title': self.title,
            'summary': self.summary,
            'verdict': self.verdict,
            'key_metrics': json.loads(self.key_metrics) if self.key_metrics else [],
            'findings': json.loads(self.findings) if self.findings else [],
            'decisions': json.loads(self.decisions) if self.decisions else [],
            'next_steps': json.loads(self.next_steps) if self.next_steps else [],
            'group_review_ids': json.loads(self.group_review_ids) if self.group_review_ids else [],
            'risks': json.loads(self.risks) if self.risks else [],
            'status': self.status,
            'manager_id': self.manager_id,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
            'reviewed_by': self.reviewed_by,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'review_comment': self.review_comment,
            'submission_count': self.submission_count,
            'resubmitted_at': self.resubmitted_at.isoformat() if self.resubmitted_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'snapshot_provenance': self.snapshot_provenance(),
        }
        if self.aggregate:
            try:
                result['aggregate'] = json.loads(self.aggregate)
            except (json.JSONDecodeError, TypeError):
                result['aggregate'] = None
        return result

    def snapshot_provenance(self):
        if not self.snapshot_id:
            return {
                'binding': 'legacy_live_unbound',
                'label': 'Legacy / live-unbound',
                'verified': None,
            }
        copy_checksum = (
            hashlib.sha256(self.snapshot_data.encode('utf-8')).hexdigest()
            if self.snapshot_data else ''
        )
        return {
            'binding': 'frozen',
            'label': 'Frozen snapshot',
            'id': self.snapshot_id,
            'checksum': self.snapshot_checksum,
            'week_start': (
                self.snapshot_week_start.isoformat()
                if self.snapshot_week_start else None
            ),
            'schema_version': self.snapshot_schema_version,
            'config_version': self.snapshot_config_version,
            'copy_verified': bool(
                self.snapshot_data and copy_checksum == self.snapshot_checksum
            ),
        }


class ReviewSnapshot(models.Model):
    """Immutable review-input snapshot in the project's database.

    This is distinct from ``DataSnapshot``, which is an operational rollback
    artifact, and from ``ReviewFile``, which stores attachment metadata.
    """
    project_id = models.IntegerField(db_index=True)
    subsystem_review = models.ForeignKey(SubsystemReview, on_delete=models.SET_NULL, null=True, blank=True, related_name='snapshots')
    week_start = models.DateField(null=True, blank=True, db_index=True)
    schema_version = models.PositiveSmallIntegerField(default=1)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')
    snapshot_type = models.CharField(max_length=20, default='milestone')
    frozen_data = models.TextField()
    record_count = models.IntegerField(default=0)
    file_count = models.IntegerField(default=0)
    checksum = models.CharField(max_length=64)
    created_by = models.IntegerField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'review_snapshots'
        verbose_name = 'Review 快照'
        verbose_name_plural = 'Review 快照'
        constraints = [
            models.UniqueConstraint(
                fields=('project_id', 'snapshot_type', 'week_start'),
                name='uq_review_snapshot_project_type_week',
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            database = kwargs.get('using') or self._state.db
            original = type(self).objects.using(database).get(pk=self.pk)
            immutable_fields = (
                'project_id', 'week_start', 'schema_version', 'snapshot_type',
                'frozen_data', 'checksum', 'created_by', 'created_at',
            )
            if any(
                getattr(self, field) != getattr(original, field)
                for field in immutable_fields
            ):
                raise ValueError('review snapshot frozen input is immutable')
        return super().save(*args, **kwargs)

    def verify_integrity(self):
        return self.checksum == DataSnapshot.compute_checksum(self.frozen_data)

    def to_dict(self, include_data=False):
        result = {
            'id': self.id,
            'kind': 'review_input_snapshot',
            'project_id': self.project_id,
            'subsystem_review_id': self.subsystem_review_id,
            'week_start': self.week_start.isoformat() if self.week_start else None,
            'schema_version': self.schema_version,
            'name': self.name,
            'description': self.description,
            'snapshot_type': self.snapshot_type,
            'record_count': self.record_count,
            'file_count': self.file_count,
            'checksum': self.checksum,
            'verified': self.verify_integrity(),
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'files': [f.to_dict() for f in self.files.all()],
        }
        if include_data:
            try:
                result['frozen_data'] = json.loads(self.frozen_data) if self.frozen_data else {}
            except (json.JSONDecodeError, TypeError):
                result['frozen_data'] = {}
        return result


class ReviewFile(models.Model):
    """Review 附件 - 项目库"""
    snapshot = models.ForeignKey(ReviewSnapshot, on_delete=models.CASCADE, related_name='files')
    filename = models.CharField(max_length=500)
    content_type = models.CharField(max_length=100, blank=True, default='')
    category = models.CharField(max_length=50, default='rpt')
    file_size = models.IntegerField(null=True, blank=True)
    storage_path = models.CharField(max_length=1000)
    checksum = models.CharField(max_length=64)
    description = models.TextField(blank=True, default='')
    uploaded_by = models.IntegerField()
    uploaded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'review_files'
        verbose_name = 'Review 附件'
        verbose_name_plural = 'Review 附件'

    def to_dict(self):
        return {
            'id': self.id,
            'snapshot_id': self.snapshot_id,
            'filename': self.filename,
            'content_type': self.content_type,
            'category': self.category,
            'file_size': self.file_size,
            'file_size_kb': round(self.file_size / 1024, 1) if self.file_size else 0,
            'checksum': self.checksum[:12] if self.checksum else None,
            'description': self.description,
            'uploaded_by': self.uploaded_by,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
        }