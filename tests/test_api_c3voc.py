import pytest

from models import event_year
from models.content import Occurrence, ScheduleItem


@pytest.fixture
def occurrence(db, user):
    occurrence = Occurrence(
        occurrence_num=1,
        video_privacy="public",
        schedule_item=ScheduleItem(
            type="talk",
            user=user,
            title="Title",
            description="Description",
            default_video_privacy="public",
        ),
    )

    db.session.add(occurrence)
    db.session.commit()

    # Fixture lifetime
    yield occurrence

    # Teardown
    db.session.delete(occurrence)
    db.session.commit()


@pytest.fixture
def valid_auth_headers():
    return {"Authorization": "Bearer video-api-test-token"}


def test_denies_request_without_api_key(client, app, occurrence):
    rv = client.post(
        "/api/occurrence/c3voc-publishing-webhook",
        json={
            "is_master": True,
            "fahrplan": {
                "conference": "emf1970",
                "id": occurrence.id,
            },
            "voctoweb": {
                "enabled": False,
            },
            "youtube": {
                "enabled": False,
            },
        },
    )
    assert rv.status_code == 401


def test_denies_request_no_master(client, app, occurrence, valid_auth_headers):
    rv = client.post(
        "/api/occurrence/c3voc-publishing-webhook",
        headers=valid_auth_headers,
        json={
            "is_master": False,
            "fahrplan": {
                "conference": "emf1970",
                "id": occurrence.id,
            },
            "voctoweb": {
                "enabled": False,
            },
            "youtube": {
                "enabled": False,
            },
        },
    )
    assert rv.status_code == 403


def test_denies_request_wrong_year(client, app, occurrence, valid_auth_headers):
    rv = client.post(
        "/api/occurrence/c3voc-publishing-webhook",
        headers=valid_auth_headers,
        json={
            "is_master": True,
            "fahrplan": {
                "conference": "emf1970",
                "id": occurrence.id,
            },
            "voctoweb": {
                "enabled": False,
            },
            "youtube": {
                "enabled": False,
            },
        },
    )
    assert rv.status_code == 422


def test_request_none_unchanged(client, app, db, occurrence, valid_auth_headers):
    rv = client.post(
        "/api/occurrence/c3voc-publishing-webhook",
        headers=valid_auth_headers,
        json={
            "is_master": True,
            "fahrplan": {
                "conference": f"emf{event_year()}",
                "id": occurrence.id,
            },
            "voctoweb": {
                "enabled": False,
            },
            "youtube": {
                "enabled": False,
            },
        },
    )
    assert rv.status_code == 204

    occurrence = db.session.get(Occurrence, occurrence.id)
    assert occurrence.youtube_url is None
    assert occurrence.c3voc_url is None


def test_update_voctoweb_with_correct_url(client, app, db, occurrence, valid_auth_headers):
    occurrence.video_recording_lost = True
    db.session.commit()

    rv = client.post(
        "/api/occurrence/c3voc-publishing-webhook",
        headers=valid_auth_headers,
        json={
            "is_master": True,
            "fahrplan": {
                "conference": f"emf{event_year()}",
                "id": occurrence.id,
            },
            "voctoweb": {
                "enabled": True,
                "frontend_url": "https://media.ccc.de/",
                "thumb_path": "",
            },
            "youtube": {
                "enabled": False,
            },
        },
    )
    assert rv.status_code == 204

    occurrence = db.session.get(Occurrence, occurrence.id)
    assert occurrence.c3voc_url == "https://media.ccc.de/"
    assert occurrence.video_recording_lost is False
    assert occurrence.youtube_url is None


def test_denies_voctoweb_with_wrong_url(client, app, db, occurrence, valid_auth_headers):
    occurrence.c3voc_url = "https://example.com"
    occurrence.video_recording_lost = True
    db.session.commit()

    rv = client.post(
        "/api/occurrence/c3voc-publishing-webhook",
        headers=valid_auth_headers,
        json={
            "is_master": True,
            "fahrplan": {
                "conference": f"emf{event_year()}",
                "id": occurrence.id,
            },
            "voctoweb": {
                "enabled": True,
                "frontend_url": "https://example.org",
                "thumb_path": "",
            },
            "youtube": {
                "enabled": False,
            },
        },
    )
    assert rv.status_code == 406

    occurrence = db.session.get(Occurrence, occurrence.id)
    # setup sets this to true, the api should not change that
    assert occurrence.video_recording_lost is True
    assert occurrence.c3voc_url == "https://example.com"


def test_clears_voctoweb(client, app, db, occurrence, valid_auth_headers):
    occurrence.c3voc_url = "https://example.com"
    db.session.commit()

    rv = client.post(
        "/api/occurrence/c3voc-publishing-webhook",
        headers=valid_auth_headers,
        json={
            "is_master": True,
            "fahrplan": {
                "conference": f"emf{event_year()}",
                "id": occurrence.id,
            },
            "voctoweb": {
                "enabled": True,
                "frontend_url": "",
                "thumb_path": "",
            },
            "youtube": {
                "enabled": False,
            },
        },
    )
    assert rv.status_code == 204

    occurrence = db.session.get(Occurrence, occurrence.id)
    assert occurrence.c3voc_url is None


def test_update_thumbnail_with_path(client, app, db, occurrence, valid_auth_headers):
    rv = client.post(
        "/api/occurrence/c3voc-publishing-webhook",
        headers=valid_auth_headers,
        json={
            "is_master": True,
            "fahrplan": {
                "conference": f"emf{event_year()}",
                "id": occurrence.id,
            },
            "voctoweb": {
                "enabled": True,
                "frontend_url": "",
                "thumb_path": "/static.media.ccc.de/thumb.jpg",
            },
            "youtube": {
                "enabled": False,
            },
        },
    )
    assert rv.status_code == 204

    occurrence = db.session.get(Occurrence, occurrence.id)
    assert occurrence.thumbnail_url == "https://static.media.ccc.de/media/thumb.jpg"
    assert occurrence.c3voc_url is None
    assert occurrence.youtube_url is None


def test_update_thumbnail_with_url(client, app, db, occurrence, valid_auth_headers):
    rv = client.post(
        "/api/occurrence/c3voc-publishing-webhook",
        headers=valid_auth_headers,
        json={
            "is_master": True,
            "fahrplan": {
                "conference": f"emf{event_year()}",
                "id": occurrence.id,
            },
            "voctoweb": {
                "enabled": True,
                "frontend_url": "",
                "thumb_path": "https://example.com/thumb.jpg",
            },
            "youtube": {
                "enabled": False,
            },
        },
    )
    assert rv.status_code == 204

    occurrence = db.session.get(Occurrence, occurrence.id)
    assert occurrence.thumbnail_url == "https://example.com/thumb.jpg"
    assert occurrence.c3voc_url is None
    assert occurrence.youtube_url is None


def test_denies_thumbnail_not_url(client, app, db, occurrence, valid_auth_headers):
    occurrence.thumbnail_url = "https://example.com/thumb.jpg"
    db.session.commit()

    rv = client.post(
        "/api/occurrence/c3voc-publishing-webhook",
        headers=valid_auth_headers,
        json={
            "is_master": True,
            "fahrplan": {
                "conference": f"emf{event_year()}",
                "id": occurrence.id,
            },
            "voctoweb": {
                "enabled": True,
                "frontend_url": "",
                "thumb_path": "/example.com/thumb.jpg",
            },
            "youtube": {
                "enabled": False,
            },
        },
    )
    assert rv.status_code == 406

    occurrence = db.session.get(Occurrence, occurrence.id)
    assert occurrence.thumbnail_url == "https://example.com/thumb.jpg"


def test_clears_thumbnail(client, app, db, occurrence, valid_auth_headers):
    occurrence.thumbnail_url = "https://example.com/thumb.jpg"
    db.session.commit()

    rv = client.post(
        "/api/occurrence/c3voc-publishing-webhook",
        headers=valid_auth_headers,
        json={
            "is_master": True,
            "fahrplan": {
                "conference": f"emf{event_year()}",
                "id": occurrence.id,
            },
            "voctoweb": {
                "enabled": True,
                "frontend_url": "",
                "thumb_path": "",
            },
            "youtube": {
                "enabled": False,
            },
        },
    )
    assert rv.status_code == 204

    occurrence = db.session.get(Occurrence, occurrence.id)
    assert occurrence.thumbnail_url is None


def test_update_from_youtube_with_correct_url(client, app, db, occurrence, valid_auth_headers):
    occurrence.video_recording_lost = True
    db.session.commit()

    rv = client.post(
        "/api/occurrence/c3voc-publishing-webhook",
        headers=valid_auth_headers,
        json={
            "is_master": True,
            "fahrplan": {
                "conference": f"emf{event_year()}",
                "id": occurrence.id,
            },
            "voctoweb": {
                "enabled": False,
            },
            "youtube": {
                "enabled": True,
                "urls": [
                    "https://www.youtube.com/watch",
                ],
            },
        },
    )
    assert rv.status_code == 204

    occurrence = db.session.get(Occurrence, occurrence.id)
    assert occurrence.c3voc_url is None
    assert occurrence.video_recording_lost is False
    assert occurrence.youtube_url == "https://www.youtube.com/watch"


def test_denies_youtube_update_with_existing_url(client, app, db, occurrence, valid_auth_headers):
    occurrence.youtube_url = "https://example.com"
    occurrence.video_recording_lost = True
    db.session.commit()

    rv = client.post(
        "/api/occurrence/c3voc-publishing-webhook",
        headers=valid_auth_headers,
        json={
            "is_master": True,
            "fahrplan": {
                "conference": f"emf{event_year()}",
                "id": occurrence.id,
            },
            "voctoweb": {
                "enabled": False,
            },
            "youtube": {
                "enabled": True,
                "urls": [
                    "https://www.youtube.com/watch",
                ],
            },
        },
    )
    assert rv.status_code == 204

    occurrence = db.session.get(Occurrence, occurrence.id)
    # setup sets this to true, the api should not change that
    assert occurrence.video_recording_lost is True
    assert occurrence.youtube_url == "https://example.com"


def test_denies_youtube_update_with_wrong_url(client, app, db, occurrence, valid_auth_headers):
    occurrence.youtube_url = "https://example.com"
    occurrence.video_recording_lost = True
    db.session.commit()

    rv = client.post(
        "/api/occurrence/c3voc-publishing-webhook",
        headers=valid_auth_headers,
        json={
            "is_master": True,
            "fahrplan": {
                "conference": f"emf{event_year()}",
                "id": occurrence.id,
            },
            "voctoweb": {
                "enabled": False,
            },
            "youtube": {
                "enabled": True,
                "urls": [
                    "https://example.org",
                ],
            },
        },
    )
    assert rv.status_code == 406

    occurrence = db.session.get(Occurrence, occurrence.id)
    # setup sets this to true, the api should not change that
    assert occurrence.video_recording_lost is True
    assert occurrence.youtube_url == "https://example.com"


def test_clears_youtube(client, app, db, occurrence, valid_auth_headers):
    occurrence.youtube_url = "https://example.com"
    db.session.commit()

    rv = client.post(
        "/api/occurrence/c3voc-publishing-webhook",
        headers=valid_auth_headers,
        json={
            "is_master": True,
            "fahrplan": {
                "conference": f"emf{event_year()}",
                "id": occurrence.id,
            },
            "voctoweb": {
                "enabled": False,
            },
            "youtube": {
                "enabled": True,
                "urls": [],
            },
        },
    )
    assert rv.status_code == 204

    occurrence = db.session.get(Occurrence, occurrence.id)
    assert occurrence.youtube_url is None
