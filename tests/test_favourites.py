import pytest
from sqlalchemy import delete, select

from apps.config import config
from models.content.schedule import FavouriteScheduleItem, ScheduleItem
from models.user import User


@pytest.fixture(scope="module")
def schedule_item(db):
    schedule_item = ScheduleItem(
        type="talk",
        user=User("favourites_speaker@example.com", "A Speaker"),
        title="A talk to favourite",
        description="A description",
    )
    db.session.add(schedule_item)
    db.session.commit()

    return schedule_item


@pytest.fixture(autouse=True)
def no_favourites(db):
    db.session.execute(delete(FavouriteScheduleItem))
    db.session.commit()


@pytest.fixture
def line_up_enabled(app):
    """Enable the LINE_UP feature flag, which the favourites page is gated on."""
    old_value = app.config.get("LINE_UP", False)
    app.config["LINE_UP"] = True
    yield
    app.config["LINE_UP"] = old_value


def favourite_rows(db, user, schedule_item):
    return db.session.execute(
        select(FavouriteScheduleItem).where(
            FavouriteScheduleItem.c.user_id == user.id,
            FavouriteScheduleItem.c.schedule_item_id == schedule_item.id,
        )
    ).all()


def insert_favourite_row(db, user, schedule_item):
    db.session.execute(
        FavouriteScheduleItem.insert().values(user_id=user.id, schedule_item_id=schedule_item.id)
    )
    db.session.commit()


def item_url(schedule_item):
    return f"/schedule/{config.event_year}/{schedule_item.id}-{schedule_item.slug}"


def last_flash(client):
    with client.session_transaction() as session:
        return session["_flashes"][-1][1]


def test_toggle_favourite(db, user, schedule_item):
    assert user.toggle_favourite(schedule_item) is True
    db.session.commit()
    assert schedule_item in user.favourites

    assert user.toggle_favourite(schedule_item) is False
    db.session.commit()
    assert schedule_item not in user.favourites


def test_set_favourite(db, user, schedule_item):
    user.set_favourite(schedule_item, True)
    db.session.commit()
    assert schedule_item in user.favourites

    user.set_favourite(schedule_item, False)
    db.session.commit()
    assert schedule_item not in user.favourites


def test_add_favourite_that_already_exists(db, user, schedule_item):
    insert_favourite_row(db, user, schedule_item)

    user.set_favourite(schedule_item, True)
    db.session.commit()

    assert len(favourite_rows(db, user, schedule_item)) == 1


def test_remove_favourite_that_no_longer_exists(db, user, schedule_item):
    user.set_favourite(schedule_item, False)
    db.session.commit()

    assert schedule_item not in user.favourites


def test_toggle_favourite_that_already_exists(db, user, schedule_item):
    insert_favourite_row(db, user, schedule_item)

    assert user.toggle_favourite(schedule_item) is False
    db.session.commit()

    assert schedule_item not in user.favourites


def test_favourite_api_requires_login(client, schedule_item):
    rv = client.get(f"/api/schedule-item/{schedule_item.id}/favourite")
    assert rv.status_code == 401

    rv = client.put(f"/api/schedule-item/{schedule_item.id}/favourite", json={})
    assert rv.status_code == 401


def test_favourite_api_toggle(db, logged_in_client, user, schedule_item):
    url = f"/api/schedule-item/{schedule_item.id}/favourite"

    rv = logged_in_client.get(url)
    assert rv.json == {"is_favourite": False}

    rv = logged_in_client.put(url, json={})
    assert rv.json == {"is_favourite": True}
    assert len(favourite_rows(db, user, schedule_item)) == 1

    rv = logged_in_client.put(url, json={})
    assert rv.json == {"is_favourite": False}
    assert len(favourite_rows(db, user, schedule_item)) == 0


def test_favourite_api_set_state_is_idempotent(db, logged_in_client, user, schedule_item):
    url = f"/api/schedule-item/{schedule_item.id}/favourite"

    for _ in range(2):
        rv = logged_in_client.put(url, json={"state": True})
        assert rv.json == {"is_favourite": True}
    assert len(favourite_rows(db, user, schedule_item)) == 1

    for _ in range(2):
        rv = logged_in_client.put(url, json={"state": False})
        assert rv.json == {"is_favourite": False}
    assert len(favourite_rows(db, user, schedule_item)) == 0


def test_add_favourite_view_requires_login(client, schedule_item):
    rv = client.post("/schedule/add-favourite", data={"fave": schedule_item.id})
    assert rv.status_code == 401


def test_add_favourite_view_toggles(db, logged_in_client, user, schedule_item):
    rv = logged_in_client.post("/schedule/add-favourite", data={"fave": schedule_item.id})
    assert rv.status_code == 302
    assert len(favourite_rows(db, user, schedule_item)) == 1

    rv = logged_in_client.post("/schedule/add-favourite", data={"fave": schedule_item.id})
    assert rv.status_code == 302
    assert len(favourite_rows(db, user, schedule_item)) == 0


def test_favourites_page_toggles(db, logged_in_client, user, schedule_item, line_up_enabled):
    rv = logged_in_client.post("/favourites", data={"fave": schedule_item.id})
    assert rv.status_code == 302
    assert len(favourite_rows(db, user, schedule_item)) == 1

    rv = logged_in_client.post("/favourites", data={"fave": schedule_item.id})
    assert rv.status_code == 302
    assert len(favourite_rows(db, user, schedule_item)) == 0


def test_item_page_toggles_favourite(db, logged_in_client, user, schedule_item):
    url = item_url(schedule_item)

    rv = logged_in_client.post(url, data={"toggle_favourite": "Favourite"})
    assert rv.status_code == 302
    assert len(favourite_rows(db, user, schedule_item)) == 1
    assert last_flash(logged_in_client) == f'Added "{schedule_item.title}" to favourites'

    rv = logged_in_client.post(url, data={"toggle_favourite": "Favourite"})
    assert rv.status_code == 302
    assert len(favourite_rows(db, user, schedule_item)) == 0
    assert last_flash(logged_in_client) == f'Removed "{schedule_item.title}" from favourites'
