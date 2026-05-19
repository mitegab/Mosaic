import factory
from factory.django import DjangoModelFactory
from mosaic_core.models import User, UserProfile, BlogPost, PostComment

class UserFactory(DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    username = factory.Sequence(lambda n: f"user_{n}")
    is_active = True

class UserProfileFactory(DjangoModelFactory):
    class Meta:
        model = UserProfile

    user = factory.SubFactory(UserFactory)
    bio = factory.Faker('paragraph')
    avatar_url = factory.Faker('image_url')
    phone = factory.Faker('phone_number')

class BlogPostFactory(DjangoModelFactory):
    class Meta:
        model = BlogPost

    author = factory.SubFactory(UserFactory)
    title = factory.Faker('sentence')
    content = factory.Faker('text')
    status = factory.Iterator(['published', 'draft', 'archived'])
    metadata = factory.LazyFunction(lambda: {"category": "Technology", "views": 100, "tags": ["orm", "django"]})
    published_at = factory.Faker('date_time_this_year')

class PostCommentFactory(DjangoModelFactory):
    class Meta:
        model = PostComment

    post = factory.SubFactory(BlogPostFactory)
    author = factory.SubFactory(UserFactory)
    body = factory.Faker('paragraph')
    rating = factory.Iterator([1, 2, 3, 4, 5])
