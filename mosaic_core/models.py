from django.db import models

class User(models.Model):
    email = models.CharField(max_length=255, unique=True)
    username = models.CharField(max_length=150, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'auth_users'
        indexes = [
            models.Index(fields=['email'], name='idx_users_email'),
            models.Index(fields=['username'], name='idx_users_username'),
        ]

    def __str__(self):
        return self.username
