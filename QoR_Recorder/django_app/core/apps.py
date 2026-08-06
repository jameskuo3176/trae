from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'django_app.core'
    label = 'core'
    verbose_name = 'QoR Recorder Core'