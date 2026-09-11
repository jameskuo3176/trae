"""Django management command: 自定义 runserver

启动前:
  1. 若为 SQLite, 执行数据库备份
  2. 初始化默认数据
  3. 记录启动信息 (与 Flask app.py 保持一致)
"""
import logging
import os

from django.conf import settings
from django.core.management.commands.runserver import Command as RunserverCommand

logger = logging.getLogger(__name__)


class Command(RunserverCommand):
    help = '启动开发服务器 (可选自动备份与默认数据初始化)'

    def run(self, **options):
        # 启动前任务
        self._startup_backup()
        self._init_default_data()
        self._print_banner(options)

        # 调用父类 runserver
        super().run(**options)

    def _startup_backup(self):
        """若为 SQLite, 执行数据库备份"""
        if not getattr(settings, 'AUTO_BACKUP_ENABLED', False):
            logger.info('[BACKUP] 自动备份已关闭 (设置 AUTO_BACKUP_ENABLED=1 可启用)')
            return
        db_type = getattr(settings, 'DB_TYPE', 'sqlite')
        if db_type != 'sqlite':
            logger.info(
                '[BACKUP] %s 后端, 跳过本地文件备份 (请确保后端已配置备份策略)',
                db_type,
            )
            return

        db_path = settings.DATABASES.get('default', {}).get('NAME', '')
        if not db_path or not os.path.exists(db_path):
            logger.warning('[BACKUP] 数据库文件不存在, 跳过备份: %s', db_path)
            return

        try:
            from django_app.services.backup_service import perform_backup
            result = perform_backup(backup_type='auto', user=None)
            if result.get('ok'):
                logger.info(
                    '[BACKUP] 已备份 DB -> %s (%sKB)',
                    result['file_path'],
                    result['file_size'] // 1024,
                )
            else:
                logger.error('[BACKUP] 备份失败(不影响启动): %s', result.get('error'))
        except Exception:
            logger.exception('[BACKUP] 备份异常(不影响启动)')

    def _init_default_data(self):
        """初始化默认数据"""
        try:
            from django.core.management import call_command
            call_command('init_default_data')
        except Exception:
            logger.exception('[INIT] 默认数据初始化异常')

    def _print_banner(self, options=None):
        """记录启动信息"""
        options = options or {}
        db_type = getattr(settings, 'DB_TYPE', 'sqlite')
        db_config = settings.DATABASES.get('default', {})
        sql_uri = db_config.get('NAME', '') or db_config.get('ENGINE', '')

        logger.info('[DB] 后端类型: %s', db_type.upper())
        if db_type == 'mongodb':
            mongo_uri = getattr(settings, 'MONGODB_URI', '')
            mongo_db = getattr(settings, 'MONGODB_DB', '')
            logger.info('[DB] MongoDB: %s db=%s', mongo_uri, mongo_db)
            logger.info('[DB] Fallback: %s (只读回退)', sql_uri)
        else:
            # 隐藏密码
            safe_uri = sql_uri
            if '@' in safe_uri:
                safe_uri = safe_uri.split('@', 1)[0] + '@***'
            logger.info('[DB] URI: %s', safe_uri)

        host = getattr(settings, 'HOST', '0.0.0.0')
        port = getattr(settings, 'PORT', 5000)
        addrport = options.get('addrport')
        if addrport:
            if ':' in addrport:
                host, raw_port = addrport.rsplit(':', 1)
                if raw_port.isdigit():
                    port = int(raw_port)
            elif addrport.isdigit():
                port = int(addrport)
        debug = getattr(settings, 'DEBUG', False)

        logger.info('QoR Recorder 系统启动中')
        logger.info('进程标识: pid=%s cwd=%s', os.getpid(), os.getcwd())
        logger.info('主数据库: %s', os.path.abspath(str(sql_uri)))
        logger.warning('默认管理员: admin / admin@2026 (首次登录请立即修改)')
        logger.info('默认用户: user / user@2026')
        logger.info('监听地址: %s:%s (debug=%s)', host, port, debug)
        logger.info(
            '安全: SECRET_KEY=%s Cookie Secure=%s',
            (
                '默认值(仅DEBUG)'
                if settings.SECRET_KEY == getattr(settings, '_DEFAULT_SECRET_KEY', '')
                else '已配置'
            ),
            getattr(settings, 'SESSION_COOKIE_SECURE', False),
        )
        if host in ('0.0.0.0', '::'):
            logger.info('访问地址: http://localhost:%s (或 http://<本机IP>:%s)', port, port)
        else:
            logger.info('访问地址: http://%s:%s', host, port)