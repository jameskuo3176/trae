"""Django management command: 自定义 runserver

启动前:
  1. 若为 SQLite, 执行数据库备份
  2. 初始化默认数据
  3. 打印启动横幅 (与 Flask app.py 保持一致)
"""
import os

from django.conf import settings
from django.core.management.commands.runserver import Command as RunserverCommand


class Command(RunserverCommand):
    help = '启动开发服务器 (含自动备份与默认数据初始化)'

    def run(self, **options):
        # 启动前任务
        self._startup_backup()
        self._init_default_data()
        self._print_banner()

        # 调用父类 runserver
        super().run(**options)

    def _startup_backup(self):
        """若为 SQLite, 执行数据库备份"""
        db_type = getattr(settings, 'DB_TYPE', 'sqlite')
        if db_type != 'sqlite':
            print(f'[BACKUP] {db_type} 后端, 跳过本地文件备份 (请确保后端已配置备份策略)')
            return

        db_path = settings.DATABASES.get('default', {}).get('NAME', '')
        if not db_path or not os.path.exists(db_path):
            print(f'[BACKUP] 数据库文件不存在, 跳过备份: {db_path}')
            return

        try:
            from django_app.services.backup_service import perform_backup
            result = perform_backup(backup_type='auto', user=None)
            if result.get('ok'):
                print(
                    f"[BACKUP] 已备份 DB -> {result['file_path']} "
                    f"({result['file_size'] // 1024}KB)"
                )
            else:
                print(f"[BACKUP] 备份失败(不影响启动): {result.get('error')}")
        except Exception as e:
            print(f'[BACKUP] 备份异常(不影响启动): {e}')

    def _init_default_data(self):
        """初始化默认数据"""
        try:
            from django.core.management import call_command
            call_command('init_default_data')
        except Exception as e:
            print(f'[INIT] 默认数据初始化异常: {e}')

    def _print_banner(self):
        """打印启动横幅"""
        db_type = getattr(settings, 'DB_TYPE', 'sqlite')
        db_config = settings.DATABASES.get('default', {})
        sql_uri = db_config.get('NAME', '') or db_config.get('ENGINE', '')

        print('=' * 60)
        print(f'[DB] 后端类型: {db_type.upper()}')
        if db_type == 'mongodb':
            mongo_uri = getattr(settings, 'MONGODB_URI', '')
            mongo_db = getattr(settings, 'MONGODB_DB', '')
            print(f'[DB] MongoDB:   {mongo_uri}  db={mongo_db}')
            print(f'[DB] Fallback:  {sql_uri}  (只读回退)')
        else:
            # 隐藏密码
            safe_uri = sql_uri
            if '@' in safe_uri:
                safe_uri = safe_uri.split('@', 1)[0] + '@***'
            print(f'[DB] URI:       {safe_uri}')

        host = getattr(settings, 'HOST', '0.0.0.0')
        port = getattr(settings, 'PORT', 5000)
        debug = getattr(settings, 'DEBUG', False)

        print('=' * 60)
        print('QoR Recorder 系统启动中...')
        print('默认管理员: admin / admin@2026  (首次登录请立即修改)')
        print('默认用户:   user / user@2026')
        print(f'监听地址:   {host}:{port}  (debug={debug})')
        print(
            f'安全:       SECRET_KEY='
            f'{"默认值(仅DEBUG)" if settings.SECRET_KEY == getattr(settings, "_DEFAULT_SECRET_KEY", "") else "已配置"}'
            f'  Cookie Secure={getattr(settings, "SESSION_COOKIE_SECURE", False)}'
        )
        if host in ('0.0.0.0', '::'):
            print(f'访问地址:   http://localhost:{port}  (或 http://<本机IP>:{port})')
        else:
            print(f'访问地址:   http://{host}:{port}')
        print('=' * 60)