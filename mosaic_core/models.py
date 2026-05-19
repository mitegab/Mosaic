from django.db import models
from django.contrib.postgres.indexes import GinIndex

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


class BlogPost(models.Model):
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='posts')
    title = models.CharField(max_length=255)
    content = models.TextField()
    status = models.CharField(max_length=50, default='draft')
    metadata = models.JSONField(default=dict, blank=True)
    published_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'blog_posts'
        indexes = [
            models.Index(fields=['status'], name='idx_posts_status'),
            GinIndex(fields=['metadata'], name='idx_posts_metadata_gin'),
        ]

    def __str__(self):
        return self.title


class PostComment(models.Model):
    post = models.ForeignKey(BlogPost, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='comments')
    body = models.TextField()
    rating = models.IntegerField(default=5)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'post_comments'
        indexes = [
            models.Index(fields=['rating'], name='idx_comments_rating'),
        ]

    def __str__(self):
        return f"Comment by {self.author.username} on {self.post.title}"
