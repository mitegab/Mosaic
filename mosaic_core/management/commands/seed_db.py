import random
from django.core.management.base import BaseCommand
from django.db import transaction
from mosaic_core.models import User, UserProfile, BlogPost, PostComment
from mosaic_core.tests.factories import UserFactory, UserProfileFactory, BlogPostFactory, PostCommentFactory

class Command(BaseCommand):
    help = 'Seeds the PostgreSQL database with realistic mock data.'

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Deleting old data...")
        PostComment.objects.all().delete()
        BlogPost.objects.all().delete()
        UserProfile.objects.all().delete()
        User.objects.all().delete()

        self.stdout.write("Seeding users and profiles...")
        users = []
        for _ in range(25):
            user = UserFactory()
            UserProfileFactory(user=user)
            users.append(user)

        self.stdout.write("Seeding blog posts with GIN JSONB index targets...")
        posts = []
        categories = ["E-Commerce", "Web Development", "Databases", "AI & Analytics", "DevOps"]
        tags_pool = ["orm", "django", "postgres", "fastapi", "react", "telemetry", "analytics", "scaling", "docker"]
        
        for i in range(50):
            meta = {
                "category": random.choice(categories),
                "views": random.randint(10, 5000),
                "tags": random.sample(tags_pool, random.randint(1, 3)),
                "seo": {
                    "keywords": ["tech", "tutorial", "insights"],
                    "rating": round(random.uniform(3.0, 5.0), 1)
                }
            }
            post = BlogPostFactory(
                author=random.choice(users),
                metadata=meta,
                status=random.choice(['published', 'published', 'draft', 'archived'])
            )
            posts.append(post)

        self.stdout.write("Seeding post comments...")
        for _ in range(120):
            PostCommentFactory(
                post=random.choice(posts),
                author=random.choice(users),
                rating=random.randint(1, 5)
            )

        self.stdout.write(self.style.SUCCESS("Database seeded successfully with 25 users, 50 blog posts, and 120 comments!"))
