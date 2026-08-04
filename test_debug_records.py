"""Debug: 验证 record_ids 收集"""
import os
import sys
import json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault('DB_TYPE', 'sqlite')
os.environ.setdefault('FLASK_DEBUG', '0')

from app import app
from models import db, Project, ProjectMember, User, ApiKey, QorRecord, Module
from core.db_routing import switch_to_project

with app.app_context():
    # 重新查刚才测试创建的项目
    test_proj = 'json_upload_test_project'
    p = Project.query.filter_by(name=test_proj).first()
    if not p:
        print('no project')
        sys.exit(1)
    print(f'project_id={p.id}')

    # 切到项目库, 查 QorRecord
    with switch_to_project(p.id):
        mods = Module.query.filter_by(project_id=p.id).all()
        print(f'modules in project DB: {len(mods)}')
        for m in mods:
            print(f'  module id={m.id} name={m.name} project_id={m.project_id}')
        qors = QorRecord.query.all()
        print(f'QorRecords in project DB: {len(qors)}')
        for q in qors:
            print(f'  id={q.id} module_id={q.module_id} version={q.version} full_dir={q.full_dir}')

    # 不切, 直接查 (测试默认 routing)
    mods2 = Module.query.filter_by(project_id=p.id).all()
    print(f'modules via default routing: {len(mods2)}')
    qors2 = QorRecord.query.all()
    print(f'QorRecords via default routing: {len(qors2)}')
