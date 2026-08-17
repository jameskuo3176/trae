import json

import pytest
from django.conf import settings
from django.test import override_settings
from django.test import Client

from django_app.core.models import User


@pytest.mark.django_db
@pytest.mark.parametrize('api_key_only', [False, True])
def test_owner_can_change_own_password_through_user_endpoint(api_key_only):
    user = User.objects.create_user(
        username='password-owner',
        password='OldPassword1',
        role='owner',
        must_change_password=True,
    )
    client = Client()
    login_response = client.post(
        '/api/v1/auth/login',
        json.dumps({
            'username': 'password-owner',
            'password': 'OldPassword1',
        }),
        content_type='application/json',
    )
    assert login_response.status_code == 200, login_response.content
    api_key = login_response.json()['api_key']
    if api_key_only:
        client.cookies.pop(settings.SESSION_COOKIE_NAME, None)

    response = client.post(
        '/api/user/password',
        json.dumps({
            'old_password': 'OldPassword1',
            'new_password': 'NewPassword2',
        }),
        content_type='application/json',
        HTTP_X_API_KEY=api_key,
    )

    assert response.status_code == 200, response.content
    assert response.json() == {'ok': True, 'must_change_password': False}
    user.refresh_from_db()
    assert user.check_password('NewPassword2')
    assert user.must_change_password is False
    assert user.password_changed_at is not None


@pytest.mark.django_db
@override_settings(RATE_LIMIT_RULES={})
def test_owner_password_login_logout_relogin_lifecycle():
    user = User.objects.create_user(
        username='lifecycle-owner',
        password='OldPassword1',
        role='owner',
        must_change_password=True,
    )
    session_client = Client()
    login_response = session_client.post(
        '/api/v1/auth/login',
        json.dumps({
            'username': user.username,
            'password': 'OldPassword1',
        }),
        content_type='application/json',
    )
    assert login_response.status_code == 200, login_response.content
    api_key = login_response.json()['api_key']

    me_response = session_client.get('/api/v1/auth/me')
    assert me_response.status_code == 200
    assert me_response.json()['auth_method'] == 'session'

    change_response = session_client.post(
        '/api/user/password',
        json.dumps({
            'old_password': 'OldPassword1',
            'new_password': 'NewPassword2',
        }),
        content_type='application/json',
    )
    assert change_response.status_code == 200, change_response.content

    api_key_client = Client(HTTP_X_API_KEY=api_key)
    api_me_response = api_key_client.get('/api/v1/auth/me')
    assert api_me_response.status_code == 200
    assert api_me_response.json()['auth_method'] == 'api_key'

    logout_response = session_client.post('/api/v1/auth/logout')
    assert logout_response.status_code == 200, logout_response.content
    assert session_client.get('/api/v1/auth/me').status_code == 401

    old_password_response = Client().post(
        '/api/v1/auth/login',
        json.dumps({
            'username': user.username,
            'password': 'OldPassword1',
        }),
        content_type='application/json',
    )
    assert old_password_response.status_code == 401

    new_password_response = Client().post(
        '/api/v1/auth/login',
        json.dumps({
            'username': user.username,
            'password': 'NewPassword2',
        }),
        content_type='application/json',
    )
    assert new_password_response.status_code == 200, new_password_response.content


@pytest.mark.django_db
@override_settings(RATE_LIMIT_RULES={})
def test_builtin_user_reset_forced_change_logout_relogin_endpoint_chain():
    admin = User.objects.create_user(
        username='admin',
        password='AdminPassword1',
        role='admin',
    )
    builtin_user = User.objects.create_user(
        username='user',
        password='user@2026',
        role='owner',
    )
    admin_client = Client()
    admin_login = admin_client.post(
        '/api/v1/auth/login',
        json.dumps({
            'username': admin.username,
            'password': 'AdminPassword1',
        }),
        content_type='application/json',
    )
    assert admin_login.status_code == 200, admin_login.content

    reset_response = admin_client.post(
        f'/api/admin/users/{builtin_user.id}/reset-password',
        content_type='application/json',
    )
    assert reset_response.status_code == 200, reset_response.content
    temporary_password = reset_response.json()['reset_to']
    admin_client.post('/api/v1/auth/logout')

    user_client = Client()
    temporary_login = user_client.post(
        '/api/v1/auth/login',
        json.dumps({
            'username': 'user',
            'password': temporary_password,
        }),
        content_type='application/json',
    )
    assert temporary_login.status_code == 200, temporary_login.content
    assert temporary_login.json()['must_change_password'] is True

    change_response = user_client.post(
        '/api/user/password',
        json.dumps({
            'old_password': temporary_password,
            'new_password': 'NewBuiltinPassword2',
        }),
        content_type='application/json',
        HTTP_X_API_KEY=temporary_login.json()['api_key'],
    )
    assert change_response.status_code == 200, change_response.content
    assert user_client.post('/api/v1/auth/logout').status_code == 200

    old_login = Client().post(
        '/api/v1/auth/login',
        json.dumps({
            'username': 'user',
            'password': temporary_password,
        }),
        content_type='application/json',
    )
    assert old_login.status_code == 401
    new_login = Client().post(
        '/api/v1/auth/login',
        json.dumps({
            'username': 'user',
            'password': 'NewBuiltinPassword2',
        }),
        content_type='application/json',
    )
    assert new_login.status_code == 200, new_login.content


@pytest.mark.django_db
def test_stale_user_profile_update_cannot_restore_previous_password():
    user = User.objects.create_user(
        username='stale-user',
        password='OldPassword1',
        role='owner',
    )
    stale_user = User.objects.get(pk=user.pk)

    current_user = User.objects.get(pk=user.pk)
    current_user.set_password('NewPassword2')
    current_user.save(update_fields=['password'])

    stale_user.display_name = 'Updated from an older request'
    stale_user.save(update_fields=['display_name'])

    user.refresh_from_db()
    assert user.display_name == 'Updated from an older request'
    assert user.check_password('NewPassword2')
    assert not user.check_password('OldPassword1')


@pytest.mark.django_db
@override_settings(RATE_LIMIT_RULES={})
def test_inactive_user_cannot_use_password_or_existing_api_key():
    user = User.objects.create_user(
        username='inactive-owner',
        password='ValidPassword1',
        role='owner',
    )
    client = Client()
    login_response = client.post(
        '/api/v1/auth/login',
        json.dumps({
            'username': user.username,
            'password': 'ValidPassword1',
        }),
        content_type='application/json',
    )
    assert login_response.status_code == 200, login_response.content
    api_key = login_response.json()['api_key']

    user.is_active = False
    user.save(update_fields=['is_active'])

    password_response = Client().post(
        '/api/v1/auth/login',
        json.dumps({
            'username': user.username,
            'password': 'ValidPassword1',
        }),
        content_type='application/json',
    )
    assert password_response.status_code == 401
    assert Client(HTTP_X_API_KEY=api_key).get('/api/v1/auth/me').status_code == 401

