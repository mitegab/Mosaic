import pytest
from django.db import connection
from mosaic_core.models import User, UserProfile, BlogPost, PostComment

@pytest.mark.django_db
def test_model_fields_and_relationships():
    # Verify we can create a User, Profile, Blog Post, and Comment successfully
    user = User.objects.create(email="test@example.com", username="testuser")
    assert user.id is not None
    assert user.is_active is True

    profile = UserProfile.objects.create(user=user, bio="This is a test bio", phone="12345")
    assert profile.id is not None
    assert user.profile == profile

    post = BlogPost.objects.create(
        author=user,
        title="Test Blog Post",
        content="This is the content.",
        status="published",
        metadata={"category": "Testing", "score": 9.5}
    )
    assert post.id is not None
    assert post.metadata["category"] == "Testing"
    assert user.posts.first() == post

    comment = PostComment.objects.create(
        post=post,
        author=user,
        body="Nice post!",
        rating=5
    )
    assert comment.id is not None
    assert post.comments.first() == comment
    assert user.comments.first() == comment

@pytest.mark.django_db
def test_jsonb_and_index_presence():
    # Introspect PostgreSQL catalog to verify GIN/BTree index presence physically
    with connection.cursor() as cursor:
        # Check index type on blog_posts metadata field
        cursor.execute("""
            SELECT indexname, indexdef 
            FROM pg_indexes 
            WHERE tablename = 'blog_posts' AND indexname = 'idx_posts_metadata_gin';
        """)
        row = cursor.fetchone()
        assert row is not None, "idx_posts_metadata_gin GIN index not found in database!"
        assert "gin" in row[1].lower(), f"Expected GIN index, got index definition: {row[1]}"

        # Check index type on auth_users email field
        cursor.execute("""
            SELECT indexname, indexdef 
            FROM pg_indexes 
            WHERE tablename = 'auth_users' AND indexname = 'idx_users_email';
        """)
        row = cursor.fetchone()
        assert row is not None, "idx_users_email index not found!"
        assert "btree" in row[1].lower() or "using btree" in row[1].lower() or "unique index" in row[1].lower()
