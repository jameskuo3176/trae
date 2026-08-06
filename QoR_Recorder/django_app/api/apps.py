from django.apps import AppConfig

class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'django_app.api'
    label = 'api'
    verbose_name = 'QoR Recorder API'