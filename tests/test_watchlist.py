"""
tests/test_watchlist.py — CineLog

Tests for the watchlist service. Structure mirrors test_collection.py:
an in-memory app fixture, a sample_user and sample_film fixture, and one
assertion-focused test per behavior.
"""

import pytest
from app import create_app, db
from models import User, Film, WatchlistEntry
from services.watchlist_service import (
    add_to_watchlist,
    remove_from_watchlist,
    get_watchlist,
    AlreadyInWatchlistError,
    NotInWatchlistError,
)
from services.collection_service import FilmNotFoundError


@pytest.fixture
def app():
    """Create an isolated test app with an in-memory database."""
    app = create_app(config={
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    })
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def sample_user(app):
    """A user to use in tests."""
    with app.app_context():
        user = User(username="testuser", email="test@example.com")
        db.session.add(user)
        db.session.commit()
        return user.id


@pytest.fixture
def sample_film(app):
    """A film to use in tests."""
    with app.app_context():
        film = Film(title="Paddington 2", year=2017, genre="Comedy")
        db.session.add(film)
        db.session.commit()
        return film.id


# ── Basic add ───────────────────────────────────────────────────────────────

def test_add_to_watchlist_creates_entry(app, sample_user, sample_film):
    """Adding a valid film should create a WatchlistEntry in the database."""
    with app.app_context():
        entry = add_to_watchlist(user_id=sample_user, film_id=sample_film)

        assert entry is not None
        assert entry.user_id == sample_user
        assert entry.film_id == sample_film

        in_db = WatchlistEntry.query.filter_by(
            user_id=sample_user, film_id=sample_film
        ).first()
        assert in_db is not None


# ── Nonexistent film (Comment 3, mirrors test_collection) ────────────────────

def test_add_to_watchlist_nonexistent_film_raises(app, sample_user):
    """
    Adding a film_id that doesn't exist in the database should raise
    FilmNotFoundError, not a database integrity error.
    """
    with app.app_context():
        fake_film_id = "00000000-0000-0000-0000-000000000000"

        with pytest.raises(FilmNotFoundError):
            add_to_watchlist(user_id=sample_user, film_id=fake_film_id)


# ── Deduplication (Comment 2) ────────────────────────────────────────────────

def test_add_to_watchlist_duplicate_raises(app, sample_user, sample_film):
    """
    Adding the same film twice for one user should raise
    AlreadyInWatchlistError, not silently create a duplicate.
    """
    with app.app_context():
        add_to_watchlist(user_id=sample_user, film_id=sample_film)

        with pytest.raises(AlreadyInWatchlistError):
            add_to_watchlist(user_id=sample_user, film_id=sample_film)

        count = WatchlistEntry.query.filter_by(
            user_id=sample_user, film_id=sample_film
        ).count()
        assert count == 1


# ── Edge case (self-chosen): dedup is per-user, not global ───────────────────

def test_add_to_watchlist_dedup_is_per_user(app, sample_user, sample_film):
    """
    Deduplication is scoped to (user_id, film_id). A *different* user adding
    the same film should succeed — the dedup check must not be global.
    """
    with app.app_context():
        add_to_watchlist(user_id=sample_user, film_id=sample_film)

        other_user = User(username="other", email="other@example.com")
        db.session.add(other_user)
        db.session.commit()

        entry = add_to_watchlist(user_id=other_user.id, film_id=sample_film)
        assert entry is not None
        assert entry.user_id == other_user.id


# ── Sort order (Comment 5): date added, newest first ─────────────────────────

def test_get_watchlist_returns_newest_first(app, sample_user):
    """
    get_watchlist() should return films sorted by date_added descending,
    matching get_collection() rather than alphabetical title order.
    """
    with app.app_context():
        from datetime import datetime, timezone, timedelta

        film_a = Film(title="Alien", year=1979, genre="Horror")
        film_b = Film(title="Blade Runner", year=1982, genre="Sci-Fi")
        db.session.add_all([film_a, film_b])
        db.session.commit()

        earlier = datetime.now(timezone.utc) - timedelta(days=5)
        later = datetime.now(timezone.utc)

        # "Alien" sorts first alphabetically but was added earlier, so a
        # date-added ordering must place the later "Blade Runner" first.
        entry_a = WatchlistEntry(user_id=sample_user, film_id=film_a.id, date_added=earlier)
        entry_b = WatchlistEntry(user_id=sample_user, film_id=film_b.id, date_added=later)
        db.session.add_all([entry_a, entry_b])
        db.session.commit()

        titles = [f["title"] for f in get_watchlist(sample_user)]
        assert titles[0] == "Blade Runner"
        assert titles[1] == "Alien"


# ── remove_from_watchlist (stretch) ──────────────────────────────────────────

def test_remove_from_watchlist_removes_entry(app, sample_user, sample_film):
    """Removing an existing entry should delete it and return True."""
    with app.app_context():
        add_to_watchlist(user_id=sample_user, film_id=sample_film)

        assert remove_from_watchlist(user_id=sample_user, film_id=sample_film) is True

        remaining = WatchlistEntry.query.filter_by(
            user_id=sample_user, film_id=sample_film
        ).count()
        assert remaining == 0


def test_remove_from_watchlist_not_present_raises(app, sample_user, sample_film):
    """Removing a film that isn't on the watchlist should raise NotInWatchlistError."""
    with app.app_context():
        with pytest.raises(NotInWatchlistError):
            remove_from_watchlist(user_id=sample_user, film_id=sample_film)
