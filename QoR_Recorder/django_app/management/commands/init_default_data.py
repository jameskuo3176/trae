"""Django management command: 初始化默认数据

对应 Flask app.py 的 init_default_data() 函数。
创建默认管理员、用户、release、viewer 账号，迁移 v5 角色，创建项目 DB 文件等。
"""
import os
import secrets
import string
from datetime import datetime

from django.core.management.base import BaseCommand
from django.conf import settings

from django_app.core.models import User, Project


class Command(BaseCommand):
    help = '初始化默认数据（管理员、用户、项目 DB 等）'

    def handle(self, *args, **options):
        self._emergency_reset_admin()
        self._create_default_users()
        self._check_default_admin_password()
        self._enforce_must_change_password()
        self._init_project_dbs()
        self.stdout.write(self.style.SUCCESS('[INIT] 默认数据初始化完成'))

    def _emergency_reset_admin(self):
        """紧急重置 admin 密码 (EMERGENCY_RESET_ADMIN_PASSWORD=1)"""
        if os.environ.get('EMERGENCY_RESET_ADMIN_PASSWORD') != '1':
            return

        admin = User.objects.filter(username='admin').first()
        if admin is None:
            admin = User(username='admin', role='admin', display_name='管理员')
            admin.must_change_password = True

        alpha = string.ascii_letters + string.digits
        new_pw = ''.join(secrets.choice(alpha) for _ in range(16))
        admin.set_password(new_pw)
        admin.must_change_password = True
        admin.password_changed_at = datetime.utcnow()
        admin.save()

        self.stdout.write('=' * 60)
        self.stdout.write(self.style.WARNING(
            '[EMERGENCY] admin 密码已强制重置 (EMERGENCY_RESET_ADMIN_PASSWORD=1)'
        ))
        self.stdout.write(self.style.WARNING(f'[EMERGENCY] 新密码: {new_pw}'))
        self.stdout.write(self.style.WARNING(
            '[EMERGENCY] 请立即用此密码登录并修改为强密码, 然后取消该环境变量'
        ))
        self.stdout.write('=' * 60)

    def _create_default_users(self):
        """创建默认账户 (admin, user, release, viewer)"""
        # admin
        if User.objects.filter(username='admin').first() is None:
            admin = User(username='admin', role='admin', display_name='管理员')
            admin.set_password('admin@2026')
            admin.must_change_password = True
            admin.save()
            self.stdout.write('[INIT] 已创建 admin 账号 (admin / admin@2026)')

        # user → owner (v5 迁移)
        if User.objects.filter(username='user').first() is None:
            user = User(username='user', role='owner', display_name='普通用户')
            user.set_password('user@2026')
            user.must_change_password = True
            user.save()
            self.stdout.write('[INIT] 已创建默认 user 账号: user / user@2026')
        else:
            # v5 迁移: 历史 user 角色升级为 owner
            legacy_user = User.objects.filter(username='user', role='user').first()
            if legacy_user:
                legacy_user.role = 'owner'
                legacy_user.save(update_fields=['role'])
                self.stdout.write('[INIT] 已将 user 角色迁移为 owner (v5)')

        # release → owner (v5 迁移)
        if User.objects.filter(username='release').first() is None:
            rel = User(username='release', role='owner', display_name='Release 客户')
            rel.set_password('release@2026')
            rel.must_change_password = True
            rel.save()
            self.stdout.write(
                '[INIT] 已创建默认 release 账号: release / release@2026 (仅可查看已发布数据)'
            )
        else:
            # v5 迁移: 历史 release 角色升级为 owner
            legacy_release = User.objects.filter(username='release', role='release').first()
            if legacy_release:
                legacy_release.role = 'owner'
                legacy_release.save(update_fields=['role'])
                self.stdout.write('[INIT] 已将 release 角色迁移为 owner (v5)')

        # viewer
        if User.objects.filter(username='viewer').first() is None:
            viewer = User(username='viewer', role='viewer', display_name='只读用户')
            viewer.set_password('viewer@2026')
            viewer.must_change_password = True
            viewer.save()
            self.stdout.write('[INIT] 已创建默认 viewer 账号: viewer / viewer@2026')

    def _check_default_admin_password(self):
        """检查 admin 是否仍使用出厂默认密码"""
        admin = User.objects.filter(username='admin').first()
        if admin and (
            admin.check_password('admin123') or
            admin.check_password('admin@2026')
        ):
            self.stdout.write('=' * 60)
            self.stdout.write(self.style.WARNING(
                '[SECURITY] 警告: admin 账户仍使用出厂默认密码!'
            ))
            self.stdout.write(self.style.WARNING(
                '  当前默认: admin@2026 (或历史版本 admin123)'
            ))
            self.stdout.write(self.style.WARNING(
                '  请立即登录修改为强密码'
            ))
            self.stdout.write('=' * 60)

    def _enforce_must_change_password(self):
        """强制改密兜底: 若任何默认账号仍使用出厂默认密码, 强制标记 must_change_password"""
        _DEFAULT_PASSWORDS = {
            'admin': ['admin@2026', 'admin123'],
            'user': ['user@2026', 'user123'],
            'release': ['release@2026', 'release123'],
            'viewer': ['viewer@2026', 'viewer123'],
        }
        for uname, default_pws in _DEFAULT_PASSWORDS.items():
            u = User.objects.filter(username=uname).first()
            if u and any(u.check_password(p) for p in default_pws):
                if not u.must_change_password:
                    u.must_change_password = True
                    u.save(update_fields=['must_change_password'])
                    self.stdout.write(
                        f'[SECURITY] {uname} 仍使用出厂默认密码, 已标记 must_change_password=True'
                    )

    def _init_project_dbs(self):
        """为所有现有项目确保 DB 文件存在"""
        try:
            from django_app.core.project_db import create_project_db, project_db_path
            for proj in Project.objects.exclude(status='hidden'):
                if not proj.db_path:
                    proj.db_path = project_db_path(proj.id)
                if not os.path.exists(proj.db_path):
                    create_project_db(proj.id)
                proj.save()
            self.stdout.write('[INIT] 项目 DB 文件检查完成')
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'[INIT] 项目 DB 初始化跳过: {e}'))