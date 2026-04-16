import pytest

from models.content import Occurrence, ScheduleItem


@pytest.fixture(scope="module")
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

    return occurrence


def test_denies_request_without_api_key(client, app, occurrence):
    app.config.update(
        {
            "VIDEO_API_KEY": "api-key",
        }
    )

    rv = client.patch(
        f"/api/occurrence/{occurrence.id}",
        json={
            "youtube_url": "https://example.com/youtube.com",
            "thumbnail_url": "https://example.com/thumbnail",
            "c3voc_url": "https://example.com/media.ccc.de",
        },
    )
    assert rv.status_code == 401


def test_can_set_video_urls(client, app, occurrence):
    app.config.update(
        {
            "VIDEO_API_KEY": "api-key",
        }
    )

    rv = client.patch(
        f"/api/occurrence/{occurrence.id}",
        json={
            "youtube_url": "https://example.com/youtube.com",
            "thumbnail_url": "https://example.com/thumbnail",
            "c3voc_url": "https://example.com/media.ccc.de",
        },
        headers={
            "Authorization": "Bearer api-key",
        },
    )
    assert rv.status_code == 200

    occurrence = Occurrence.query.get(occurrence.id)
    assert occurrence.youtube_url == "https://example.com/youtube.com"
    assert occurrence.thumbnail_url == "https://example.com/thumbnail"
    assert occurrence.c3voc_url == "https://example.com/media.ccc.de"


def test_clearing_video_url(client, app, db, occurrence):
    app.config.update(
        {
            "VIDEO_API_KEY": "api-key",
        }
    )

    occurrence.youtube_url = "https://example.com/youtube.com"
    db.session.add(occurrence)
    db.session.commit()

    rv = client.patch(
        f"/api/occurrence/{occurrence.id}",
        json={
            "youtube_url": None,
        },
        headers={
            "Authorization": "Bearer api-key",
        },
    )
    assert rv.status_code == 200

    occurrence = Occurrence.query.get(occurrence.id)
    assert occurrence.youtube_url is None


def test_rejects_disallowed_attributes(client, app, occurrence):
    app.config.update(
        {
            "VIDEO_API_KEY": "api-key",
        }
    )

    rv = client.patch(
        f"/api/occurrence/{occurrence.id}",
        json={
            "youtube_url": "https://example.com/youtube.com",
            "thumbnail_url": "https://example.com/thumbnail",
            "c3voc_url": "https://example.com/media.ccc.de",
            "title": "Not allowed",
        },
        headers={
            "Authorization": "Bearer api-key",
        },
    )
    assert rv.status_code == 400
