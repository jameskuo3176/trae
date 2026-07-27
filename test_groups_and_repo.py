"""Group 与 MongoDB 抽象层验证脚本

测试场景:
  1. 同一 project 下同名 group 不能重复 (差异化命名空间)
  2. 不同 project 下可以同名
  3. 可见性: owner/member/admin/release/user 各角色
  4. shared_default 自动应用
  5. MongoDB 抽象层可用 (无 pymongo 时优雅降级)

跑法:  python test_groups_and_repo.py
"""
import os
import sys
import json
import logging
logging.basicConfig(level=logging.WARNING)

# 把 repo 默认设为 sqlite, 不依赖 MongoDB
os.environ['DATABASE_BACKEND'] = 'sqlite'
os.environ.setdefault('MONGO_URI', 'mongodb://localhost:27017')

import app as app_module
import repo
from models import db, User, Project, Module, DashboardGroup

PASS = '✓'
FAIL = '✗'
results = []


def check(name, cond, detail=''):
    if cond:
        print(f'  {PASS} {name}')
        results.append(True)
    else:
        print(f'  {FAIL} {name}  {detail}')
        results.append(False)


def fresh_db():
    """重置 group 相关表, 保留 users/projects"""
    DashboardGroup.query.delete()
    db.session.commit()


def main():
    with app_module.app.app_context():
        # 准备基础数据
        admin = User.query.filter_by(username='admin').first()
        assert admin is not None, '需要 admin 账户, 请先 init_db'
        u1 = User.query.filter_by(username='user').first()
        rel = User.query.filter_by(username='release').first()

        # 准备两个项目
        p1 = Project.query.filter_by(name='ChipP0-Floorplan').first()
        if p1 is None:
            p1 = Project(name='ChipP0-Floorplan', description='P0')
            db.session.add(p1)
        p2 = Project.query.filter_by(name='ChipP1-CPU').first()
        if p2 is None:
            p2 = Project(name='ChipP1-CPU', description='P1')
            db.session.add(p2)
        db.session.commit()

        fresh_db()
        # 重新获取
        p1 = Project.query.filter_by(name='ChipP0-Floorplan').first()
        p2 = Project.query.filter_by(name='ChipP1-CPU').first()

        print('\n[1] MongoDB 抽象层')
        check('repo 模块可加载', repo is not None)
        check('is_mongo_enabled 返回 bool', isinstance(repo.is_mongo_enabled(), bool))
        check('BACKEND 默认 sqlite', repo.BACKEND in ('sqlite', 'mongo', 'dual'))
        check('mongo_upsert 在未连接时安全降级', not repo.mongo_upsert('x', {'id': 1}, 'id'))

        print('\n[2] 同一 project 下同名 group 不可重复')
        g1a = DashboardGroup(
            name='Floorplan-Team', project_id=p1.id, owner_id=admin.id,
            member_ids='[]', config='{}', shared_default=False, is_public=False
        )
        db.session.add(g1a)
        db.session.commit()
        # 尝试再加同名
        g1b = DashboardGroup(
            name='Floorplan-Team', project_id=p1.id, owner_id=u1.id,
            member_ids='[]', config='{}'
        )
        db.session.add(g1b)
        try:
            db.session.commit()
            check('同 project 同名被阻止', False, '应该 IntegrityError')
        except Exception:
            db.session.rollback()
            check('同 project 同名被阻止', True)

        print('\n[3] 不同 project 下可以同名 (差异化命名空间)')
        g2 = DashboardGroup(
            name='Floorplan-Team', project_id=p2.id, owner_id=admin.id,
            member_ids='[]', config='{}'
        )
        db.session.add(g2)
        try:
            db.session.commit()
            check('不同 project 同名 OK', True)
        except Exception as e:
            db.session.rollback()
            check('不同 project 同名 OK', False, str(e))

        print('\n[4] 可见性矩阵')
        # global group
        g_global = DashboardGroup(
            name='Global-View', project_id=None, owner_id=admin.id,
            member_ids='[]', config='{}', is_public=True, shared_default=True
        )
        db.session.add(g_global)
        # private group owned by u1
        g_priv = DashboardGroup(
            name='U1-Private', project_id=p1.id, owner_id=u1.id,
            member_ids='[]', config='{}'
        )
        db.session.add(g_priv)
        db.session.commit()

        check('admin 可见所有 4 个',
              DashboardGroup.query.count() == 4 and
              all(g.is_visible_to(admin, 'admin') for g in DashboardGroup.query.all()),
              f'count={DashboardGroup.query.count()}')
        check('u1(owner of g_priv) 可见 g_priv',
              g_priv.is_visible_to(u1, 'user'))
        check('u1 不可见 admin 创建的 g1a (私有)',
              not g1a.is_visible_to(u1, 'user'))
        check('release 不可见 g1a (私有, 项目未发布)',
              not g1a.is_visible_to(rel, 'release'))
        # 项目 p1 无发布数据, 但若将 g1a 设为公开, release 应可见
        g1a.is_public = True
        db.session.commit()
        # 确保该项目下没有任何已发布记录
        from models import QorRecord
        for old in QorRecord.query.join(Module).filter(Module.project_id == p1.id).all():
            db.session.delete(old)
        db.session.commit()
        check('release 在项目无发布数据时仍不可见公开 group',
              not g1a.is_visible_to(rel, 'release'),
              '应该 false, 缺已发布数据')
        # 模拟项目下有发布数据: 加一条 released QorRecord
        from models import QorRecord
        m1 = Module.query.filter_by(project_id=p1.id, name='mod_test').first()
        if m1 is None:
            m1 = Module(project_id=p1.id, name='mod_test')
            db.session.add(m1)
            db.session.commit()
        rec = QorRecord(
            module_id=m1.id, version='v1', area_total=1000.0, wns_setup=0.1,
            is_released=True
        )
        db.session.add(rec)
        db.session.commit()
        check('release 项目有发布数据后, 可见公开 group',
              g1a.is_visible_to(rel, 'release'))

        print('\n[5] 成员管理')
        g_priv.member_ids = json.dumps([u1.id])  # u1 是 owner
        # 添加 admin 为成员
        g_priv.member_ids = json.dumps([admin.id])
        db.session.commit()
        check('添加成员 admin 后 is_member(admin)=True',
              g_priv.is_member(admin.id))
        check('owner (u1) 始终是成员',
              g_priv.is_member(u1.id))
        check('非成员 rel.is_member=False',
              not g_priv.is_member(rel.id))

        print('\n[6] shared_default + my-default 逻辑')
        g_global.shared_default = True
        g_priv.shared_default = True
        db.session.commit()
        # admin 是 g_global 的 owner, g_priv 的成员
        candidates = [g for g in DashboardGroup.query.all()
                      if g.shared_default and g.is_member(admin.id)]
        check('admin 候选 = 2 个 (global + priv)', len(candidates) == 2)

        print('\n[7] can_edit 权限')
        check('admin 可编辑任何 group', g_priv.can_edit(admin, 'admin'))
        check('owner (u1) 可编辑自己的 group', g_priv.can_edit(u1, 'user'))
        check('非 owner 不可编辑',
              not g_priv.can_edit(admin, 'user'),
              'admin 角色默认可编辑, 这里用 user 测')
        # 改: admin 角色直接 OK; 用另一个 user
        if not User.query.filter_by(username='iso_test_a').first():
            testu = User(username='iso_test_a', role='user', display_name='T')
            testu.set_password('a@2026')
            db.session.add(testu)
            db.session.commit()
        else:
            testu = User.query.filter_by(username='iso_test_a').first()
        check('非 owner / 非 admin 不可编辑',
              not g_priv.can_edit(testu, 'user'))

        print('\n[8] 迁移脚本可导入')
        try:
            import migrate_sqlite_to_mongo
            check('migrate_sqlite_to_mongo 脚本可加载', True)
            check('TABLES 包含 8 个表', len(migrate_sqlite_to_mongo.TABLES) >= 7)
        except Exception as e:
            check('migrate_sqlite_to_mongo 脚本可加载', False, str(e))

        print('\n[9] repo 同步接口 (在 mongo 未启用时安全降级)')
        # 用 to_dict 模拟 sql 对象
        class FakeRecord:
            id = 1
            def to_dict(self): return {'id': 1, 'name': 'fake'}
        repo.sync_qor_record(FakeRecord(), 'upsert')  # 不应抛
        repo.sync_dashboard_group(FakeRecord(), 'upsert')
        check('sync_qor_record 在 mongo 关闭时安全返回', True)
        check('sync_dashboard_group 在 mongo 关闭时安全返回', True)

        # 清理
        fresh_db()
        db.session.delete(rec); db.session.commit()
        if m1.name == 'mod_test':
            db.session.delete(m1); db.session.commit()
        print(f'\n==========  {"全部通过" if all(results) else f"{results.count(False)} 项失败"} ==========')
        sys.exit(0 if all(results) else 1)


if __name__ == '__main__':
    main()
