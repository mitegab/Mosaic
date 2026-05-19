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


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    bio = models.TextField(blank=True, null=True)
    avatar_url = models.CharField(max_length=500, blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        db_table = 'user_profiles'

    def __str__(self):
        return f"Profile of {self.user.username}"
