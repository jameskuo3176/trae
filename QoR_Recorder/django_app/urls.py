"""Django URL Configuration for QoR Recorder.

包含所有从 Flask 蓝图迁移过来的 URL 路由。
"""
import os

from django.conf import settings
from django.conf.urls.static import static
from django.urls import path

from django_app.api import views as api_views
from django_app.core import views as core_views

urlpatterns = [
    # =========================================================================
    # 页面视图
    # =========================================================================
    path('', core_views.dashboard, name='dashboard'),
    path('login/', core_views.login_view, name='login'),
    path('logout/', core_views.logout_view, name='logout'),
    path('change_password/', core_views.change_password_page, name='change_password_page'),
    path('dashboard/', core_views.dashboard, name='dashboard'),
    path('compare/', core_views.compare, name='compare'),
    path('review/', core_views.review_page, name='review'),
    path('admin/', core_views.admin_page, name='admin_page'),
    path('qor_record/<int:record_id>/', core_views.qor_record_detail_page, name='qor_record_detail_page'),
    path('dbadmin/', core_views.db_admin, name='db_admin'),
    path('dbadmin/<path:subpath>/', core_views.db_admin, name='db_admin_subpath'),

    # =========================================================================
    # QoR 数据查询 API
    # =========================================================================
    path('api/projects', api_views.api_get_projects, name='api_get_projects'),
    path('api/modules/<int:project_id>/', api_views.api_get_modules, name='api_get_modules'),
    path('api/modules/<int:project_id>/<int:module_id>/records', api_views.api_get_module_records, name='api_get_module_records'),
    path('api/qor_data', api_views.api_get_qor_data, name='api_get_qor_data'),
    path('api/qor/record/<int:record_id>/', api_views.api_qor_record_detail, name='api_qor_record_detail'),
    path('api/qor/aggregate', api_views.api_qor_aggregate, name='api_qor_aggregate'),
    path('api/qor/parse_path', api_views.api_qor_parse_path, name='api_qor_parse_path'),
    path('api/qor/dir_modules', api_views.api_dir_modules, name='api_dir_modules'),
    path('api/metrics', api_views.api_get_metrics, name='api_get_metrics'),
    path('api/versions', api_views.api_get_versions, name='api_get_versions'),
    path('api/run_notes', api_views.api_get_run_notes, name='api_get_run_notes'),
    path('api/compare', api_views.api_compare, name='api_compare'),
    path('export', api_views.export_data, name='export_data'),

    # =========================================================================
    # Review API
    # =========================================================================
    path('api/reviews/options', api_views.reviews_options, name='reviews_options'),
    path('api/reviews/tile', api_views.list_tile_reviews, name='list_tile_reviews'),
    path('api/reviews/tile/<int:rid>', api_views.tile_review_detail, name='tile_review_detail'),
    path('api/reviews/tile/<int:rid>/submit', api_views.submit_tile_review, name='submit_tile_review'),
    path('api/reviews/tile/<int:rid>/review', api_views.review_tile_review, name='review_tile_review'),
    path('api/reviews/group', api_views.list_group_reviews, name='list_group_reviews'),
    path('api/reviews/group/<int:rid>', api_views.group_review_detail, name='group_review_detail'),
    path('api/reviews/group/<int:rid>/submit', api_views.submit_group_review, name='submit_group_review'),
    path('api/reviews/group/<int:rid>/review', api_views.review_group_review, name='review_group_review'),
    path('api/reviews/subsystem', api_views.list_subsystem_reviews, name='list_subsystem_reviews'),
    path('api/reviews/subsystem/<int:rid>', api_views.subsystem_review_detail, name='subsystem_review_detail'),
    path('api/reviews/subsystem/<int:rid>/submit', api_views.submit_subsystem_review, name='submit_subsystem_review'),
    path('api/reviews/subsystem/<int:rid>/review', api_views.review_subsystem_review, name='review_subsystem_review'),
    path('api/reviews/snapshots', api_views.list_snapshots, name='list_snapshots'),
    path('api/reviews/snapshot/<int:rid>', api_views.snapshot_detail, name='snapshot_detail'),
    path('api/reviews/snapshot/<int:rid>/upload', api_views.upload_snapshot_file, name='upload_snapshot_file'),
    path('api/reviews/snapshot/<int:rid>/verify', api_views.verify_snapshot, name='verify_snapshot'),
    path('api/reviews/file/<int:fid>/download', api_views.download_review_file, name='download_review_file'),

    # =========================================================================
    # Dashboard API
    # =========================================================================
    path('api/dashboard/save', api_views.save_dashboard_config, name='save_dashboard_config'),
    path('api/dashboard/list', api_views.list_dashboard_configs, name='list_dashboard_configs'),
    path('api/dashboard/<int:dash_id>', api_views.dashboard_config_detail, name='dashboard_config_detail'),
    path('api/groups', api_views.list_dashboard_groups, name='list_dashboard_groups'),
    path('api/groups/<int:gid>', api_views.dashboard_group_detail, name='dashboard_group_detail'),
    path('api/groups/my-default', api_views.my_default_group, name='my_default_group'),
    path('api/user/theme', api_views.get_user_theme, name='get_user_theme'),

    # =========================================================================
    # Admin API - 项目管理
    # =========================================================================
    path('api/admin/projects', api_views.admin_create_project, name='admin_create_project'),
    path('api/admin/projects/<int:project_id>', api_views.admin_delete_project, name='admin_delete_project'),
    path('api/admin/projects/hidden', api_views.admin_list_hidden_projects, name='admin_list_hidden_projects'),
    path('api/admin/projects/<int:project_id>/restore', api_views.admin_restore_project, name='admin_restore_project'),
    path('api/admin/projects/<int:project_id>/hard_delete', api_views.admin_hard_delete_project, name='admin_hard_delete_project'),
    path('api/admin/projects/<int:project_id>/lock', api_views.admin_lock_project, name='admin_lock_project'),
    path('api/admin/projects/<int:project_id>/unlock', api_views.admin_unlock_project, name='admin_unlock_project'),
    path('api/admin/projects/<int:project_id>/snapshots', api_views.admin_list_snapshots, name='admin_list_snapshots'),
    path('api/admin/snapshots/<int:snap_id>', api_views.admin_snapshot_detail, name='admin_snapshot_detail'),
    path('api/admin/snapshots/<int:snap_id>/verify', api_views.admin_verify_snapshot, name='admin_verify_snapshot'),
    path('api/admin/snapshots/<int:snap_id>/rollback', api_views.admin_rollback_snapshot, name='admin_rollback_snapshot'),

    # =========================================================================
    # Admin API - 备份管理
    # =========================================================================
    path('api/admin/backups', api_views.admin_list_backups, name='admin_list_backups'),
    path('api/admin/backups/verify', api_views.admin_verify_all_backups, name='admin_verify_all_backups'),

    # =========================================================================
    # Admin API - 模块管理
    # =========================================================================
    path('api/admin/modules', api_views.admin_create_module, name='admin_create_module'),
    path('api/admin/modules/<int:module_id>', api_views.admin_delete_module, name='admin_delete_module'),
    path('api/admin/modules/batch', api_views.admin_batch_create_modules, name='admin_batch_create_modules'),
    path('api/admin/modules/<int:module_id>/collaborators', api_views.admin_module_collaborators, name='admin_module_collaborators'),
    path('api/admin/modules/<int:module_id>/collaborators/<int:user_id>', api_views.admin_remove_module_collaborator, name='admin_remove_module_collaborator'),

    # =========================================================================
    # Admin API - 用户管理
    # =========================================================================
    path('api/admin/owner_users', api_views.admin_list_owner_users, name='admin_list_owner_users'),
    path('api/admin/records/<int:record_id>', api_views.admin_delete_record, name='admin_delete_record'),
    path('api/admin/records/owners', api_views.admin_list_record_owners, name='admin_list_record_owners'),
    path('api/admin/upload', api_views.admin_upload_csv, name='admin_upload_csv'),
    path('api/admin/upload_block_qor', api_views.admin_upload_block_qor, name='admin_upload_block_qor'),
    path('api/admin/upload_csv_preview', api_views.admin_upload_csv_preview, name='admin_upload_csv_preview'),
    path('api/admin/qor/<int:record_id>/release', api_views.admin_toggle_release, name='admin_toggle_release'),
    path('api/admin/qor/<int:record_id>/release_dir', api_views.admin_update_release_dir, name='admin_update_release_dir'),
    path('api/admin/qor/<int:record_id>/description', api_views.admin_update_version_description, name='admin_update_version_description'),
    path('api/admin/qor/batch_release', api_views.admin_batch_release, name='admin_batch_release'),
    path('api/admin/users', api_views.admin_list_users, name='admin_list_users'),
    path('api/admin/users/batch', api_views.admin_batch_create_users, name='admin_batch_create_users'),
    path('api/admin/users/<int:user_id>/reset-password', api_views.admin_reset_user_password, name='admin_reset_user_password'),
    path('api/admin/user/password', api_views.user_change_own_password, name='user_change_own_password'),

    # =========================================================================
    # API v1 - 项目
    # =========================================================================
    path('api/v1/projects', api_views.api_v1_list_projects, name='api_v1_list_projects'),
    path('api/v1/projects/<int:project_id>', api_views.api_v1_get_project, name='api_v1_get_project'),
    path('api/v1/projects/<int:project_id>/members', api_views.api_v1_list_members, name='api_v1_list_members'),
    path('api/v1/projects/<int:project_id>/members/<int:member_id>', api_views.api_v1_remove_member, name='api_v1_remove_member'),

    # =========================================================================
    # API v1 - 数据锁
    # =========================================================================
    path('api/v1/locks', api_views.api_v1_list_locks, name='api_v1_list_locks'),
    path('api/v1/locks/<int:lock_id>', api_views.api_v1_release_lock, name='api_v1_release_lock'),

    # =========================================================================
    # API v1 - API Key
    # =========================================================================
    path('api/v1/apikeys', api_views.api_v1_list_apikeys, name='api_v1_list_apikeys'),
    path('api/v1/apikeys/<int:key_id>', api_views.api_v1_revoke_apikey, name='api_v1_revoke_apikey'),

    # =========================================================================
    # API v1 - 上传
    # =========================================================================
    path('api/v1/upload', api_views.api_v1_upload, name='api_v1_upload'),
    path('api/v1/qor/upload', api_views.api_v1_qor_upload_json, name='api_v1_qor_upload_json'),

    # =========================================================================
    # API v1 - 告警
    # =========================================================================
    path('api/v1/alerts/rules', api_views.api_v1_list_alert_rules, name='api_v1_list_alert_rules'),
    path('api/v1/alerts/rules/<int:rule_id>', api_views.api_v1_modify_alert_rule, name='api_v1_modify_alert_rule'),
    path('api/v1/alerts/events', api_views.api_v1_list_alert_events, name='api_v1_list_alert_events'),
    path('api/v1/alerts/events/<int:event_id>/acknowledge', api_views.api_v1_acknowledge_event, name='api_v1_acknowledge_event'),

    # =========================================================================
    # API v1 - 认证
    # =========================================================================
    path('api/v1/auth/login', api_views.api_v1_login, name='api_v1_login'),
    path('api/v1/auth/me', api_views.api_v1_me, name='api_v1_me'),

    # =========================================================================
    # Violations API
    # =========================================================================
    path('api/violations', api_views.api_get_violations, name='api_get_violations'),
    path('api/violations/source_files', api_views.api_get_violation_source_files, name='api_get_violation_source_files'),
    path('api/violations/diff', api_views.api_violations_diff, name='api_violations_diff'),
    path('api/violations/timing_groups', api_views.api_get_timing_groups, name='api_get_timing_groups'),
    path('api/violations/summary', api_views.api_get_violation_summary, name='api_get_violation_summary'),

    # =========================================================================
    # Tools API
    # =========================================================================
    path('api/tools/source-files/check', api_views.api_tools_source_files_check, name='api_tools_source_files_check'),
    path('api/tools/source-files/open', api_views.api_tools_source_files_open, name='api_tools_source_files_open'),
    path('api/tools/source-files/gvim', api_views.api_tools_source_files_gvim, name='api_tools_source_files_gvim'),
    path('tools/source-files', api_views.tools_source_files_check_page, name='tools_source_files_check_page'),
]

# =========================================================================
# 静态文件 (始终在开发模式下提供)
# =========================================================================
from django.views.static import serve
urlpatterns += [
    path('static/<path:path>', serve, {'document_root': settings.STATIC_ROOT}),
    path('uploads/<path:path>', serve, {'document_root': settings.MEDIA_ROOT}),
]