import pytest

from models import event_year
from models.cfp import Proposal, TalkProposal


@pytest.fixture(scope="module")
def proposal(db, user):
    proposal = TalkProposal()
    proposal.title = "Title"
    proposal.description = "Description"
    proposal.user = user

    db.session.add(proposal)
    db.session.commit()

    return proposal


def clean_proposal(db, proposal, c3voc_url=None, youtube_url=None, thumbnail_url=None, video_recording_lost=True):
    proposal.c3voc_url = c3voc_url
    proposal.thumbnail_url = thumbnail_url
    proposal.video_recording_lost = video_recording_lost
    proposal.youtube_url = youtube_url
    db.session.add(proposal)
    db.session.commit()


def test_denies_request_without_api_key(client, app, proposal):
    app.config.update(
        {
            "VIDEO_API_KEY": "api-key",
        }
    )

    rv = client.post(
        f"/api/proposal/c3voc-publishing-webhook",
        json={
            "is_master": True,
            "fahrplan": {
                "conference": "emf1970",
                "id": 0,
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


def test_denies_request_no_master(client, app, proposal):
    app.config.update(
        {
            "VIDEO_API_KEY": "api-key",
        }
    )

    rv = client.post(
        f"/api/proposal/c3voc-publishing-webhook",
        headers={
            "Authorization": "Bearer api-key",
        },
        json={
            "is_master": False,
            "fahrplan": {
                "conference": "emf1970",
                "id": 0,
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


def test_denies_request_wrong_year(client, app, proposal):
    app.config.update(
        {
            "VIDEO_API_KEY": "api-key",
        }
    )

    rv = client.post(
        f"/api/proposal/c3voc-publishing-webhook",
        headers={
            "Authorization": "Bearer api-key",
        },
        json={
            "is_master": True,
            "fahrplan": {
                "conference": "emf1970",
                "id": 0,
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


def test_request_none_update_none(client, app, db, proposal):
    app.config.update(
        {
            "VIDEO_API_KEY": "api-key",
        }
    )

    clean_proposal(db, proposal)

    rv = client.post(
        f"/api/proposal/c3voc-publishing-webhook",
        headers={
            "Authorization": "Bearer api-key",
        },
        json={
            "is_master": True,
            "fahrplan": {
                "conference": f"emf{event_year()}",
                "id": proposal.id,
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

    proposal = Proposal.query.get(proposal.id)
    assert proposal.youtube_url is None
    assert proposal.c3voc_url is None


def test_request_voctoweb_update_voctoweb_correct_url(client, app, db, proposal):
    app.config.update(
        {
            "VIDEO_API_KEY": "api-key",
        }
    )

    clean_proposal(db, proposal)

    rv = client.post(
        f"/api/proposal/c3voc-publishing-webhook",
        headers={
            "Authorization": "Bearer api-key",
        },
        json={
            "is_master": True,
            "fahrplan": {
                "conference": f"emf{event_year()}",
                "id": proposal.id,
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

    proposal = Proposal.query.get(proposal.id)
    assert proposal.c3voc_url == "https://media.ccc.de/"
    assert proposal.video_recording_lost == False
    assert proposal.youtube_url is None


def test_request_voctoweb_update_voctoweb_wrong_url(client, app, db, proposal):
    app.config.update(
        {
            "VIDEO_API_KEY": "api-key",
        }
    )

    clean_proposal(db, proposal, c3voc_url="https://example.com")

    rv = client.post(
        f"/api/proposal/c3voc-publishing-webhook",
        headers={
            "Authorization": "Bearer api-key",
        },
        json={
            "is_master": True,
            "fahrplan": {
                "conference": f"emf{event_year()}",
                "id": proposal.id,
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

    proposal = Proposal.query.get(proposal.id)
    # clean_proposal sets this to true, the api should not change that
    assert proposal.video_recording_lost == True
    assert proposal.c3voc_url == "https://example.com"


def test_request_voctoweb_clears_voctoweb(client, app, db, proposal):
    app.config.update(
        {
            "VIDEO_API_KEY": "api-key",
        }
    )

    clean_proposal(db, proposal, c3voc_url="https://example.com")

    rv = client.post(
        f"/api/proposal/c3voc-publishing-webhook",
        headers={
            "Authorization": "Bearer api-key",
        },
        json={
            "is_master": True,
            "fahrplan": {
                "conference": f"emf{event_year()}",
                "id": proposal.id,
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

    proposal = Proposal.query.get(proposal.id)
    assert proposal.c3voc_url is None


def test_request_thumbnail_update_thumbnail_correct_path(client, app, db, proposal):
    app.config.update(
        {
            "VIDEO_API_KEY": "api-key",
        }
    )

    clean_proposal(db, proposal)

    rv = client.post(
        f"/api/proposal/c3voc-publishing-webhook",
        headers={
            "Authorization": "Bearer api-key",
        },
        json={
            "is_master": True,
            "fahrplan": {
                "conference": f"emf{event_year()}",
                "id": proposal.id,
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

    proposal = Proposal.query.get(proposal.id)
    assert proposal.thumbnail_url  == "https://static.media.ccc.de/media/thumb.jpg"
    assert proposal.c3voc_url is None
    assert proposal.youtube_url is None


def test_request_thumbnail_update_thumbnail_correct_url(client, app, db, proposal):
    app.config.update(
        {
            "VIDEO_API_KEY": "api-key",
        }
    )

    clean_proposal(db, proposal)

    rv = client.post(
        f"/api/proposal/c3voc-publishing-webhook",
        headers={
            "Authorization": "Bearer api-key",
        },
        json={
            "is_master": True,
            "fahrplan": {
                "conference": f"emf{event_year()}",
                "id": proposal.id,
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

    proposal = Proposal.query.get(proposal.id)
    assert proposal.thumbnail_url  == "https://example.com/thumb.jpg"
    assert proposal.c3voc_url is None
    assert proposal.youtube_url is None


def test_request_thumbnail_update_thumbnail_not_url(client, app, db, proposal):
    app.config.update(
        {
            "VIDEO_API_KEY": "api-key",
        }
    )

    clean_proposal(db, proposal, thumbnail_url="https://example.com/thumb.jpg")

    rv = client.post(
        f"/api/proposal/c3voc-publishing-webhook",
        headers={
            "Authorization": "Bearer api-key",
        },
        json={
            "is_master": True,
            "fahrplan": {
                "conference": f"emf{event_year()}",
                "id": proposal.id,
            },
            "voctoweb": {
                "enabled": True,
                "frontend_url": "",
                "thumb_path": "gopher://example.com/thumb.jpg",
            },
            "youtube": {
                "enabled": False,
            },
        },
    )
    assert rv.status_code == 406

    proposal = Proposal.query.get(proposal.id)
    assert proposal.thumbnail_url == "https://example.com/thumb.jpg"


def test_request_thumbnail_clears_thumbnail(client, app, db, proposal):
    app.config.update(
        {
            "VIDEO_API_KEY": "api-key",
        }
    )

    clean_proposal(db, proposal, thumbnail_url="https://example.com/thumb.jpg")

    rv = client.post(
        f"/api/proposal/c3voc-publishing-webhook",
        headers={
            "Authorization": "Bearer api-key",
        },
        json={
            "is_master": True,
            "fahrplan": {
                "conference": f"emf{event_year()}",
                "id": proposal.id,
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

    proposal = Proposal.query.get(proposal.id)
    assert proposal.thumbnail_url is None


def test_request_youtube_update_youtube_correct_url(client, app, db, proposal):
    app.config.update(
        {
            "VIDEO_API_KEY": "api-key",
        }
    )

    clean_proposal(db, proposal)

    rv = client.post(
        f"/api/proposal/c3voc-publishing-webhook",
        headers={
            "Authorization": "Bearer api-key",
        },
        json={
            "is_master": True,
            "fahrplan": {
                "conference": f"emf{event_year()}",
                "id": proposal.id,
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

    proposal = Proposal.query.get(proposal.id)
    assert proposal.c3voc_url is None
    assert proposal.video_recording_lost == False
    assert proposal.youtube_url == "https://www.youtube.com/watch"


def test_request_youtube_update_youtube_correct_url_but_existing_url(client, app, db, proposal):
    app.config.update(
        {
            "VIDEO_API_KEY": "api-key",
        }
    )

    clean_proposal(db, proposal, youtube_url="https://example.com")

    rv = client.post(
        f"/api/proposal/c3voc-publishing-webhook",
        headers={
            "Authorization": "Bearer api-key",
        },
        json={
            "is_master": True,
            "fahrplan": {
                "conference": f"emf{event_year()}",
                "id": proposal.id,
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

    proposal = Proposal.query.get(proposal.id)
    # clean_proposal sets this to true, the api should not change that
    assert proposal.video_recording_lost == True
    assert proposal.youtube_url == "https://example.com"


def test_request_youtube_update_youtube_wrong_url(client, app, db, proposal):
    app.config.update(
        {
            "VIDEO_API_KEY": "api-key",
        }
    )

    clean_proposal(db, proposal, youtube_url="https://example.com")

    rv = client.post(
        f"/api/proposal/c3voc-publishing-webhook",
        headers={
            "Authorization": "Bearer api-key",
        },
        json={
            "is_master": True,
            "fahrplan": {
                "conference": f"emf{event_year()}",
                "id": proposal.id,
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

    proposal = Proposal.query.get(proposal.id)
    # clean_proposal sets this to true, the api should not change that
    assert proposal.video_recording_lost == True
    assert proposal.youtube_url == "https://example.com"


def test_request_youtube_clears_youtube(client, app, db, proposal):
    app.config.update(
        {
            "VIDEO_API_KEY": "api-key",
        }
    )

    clean_proposal(db, proposal, youtube_url="https://example.com")

    rv = client.post(
        f"/api/proposal/c3voc-publishing-webhook",
        headers={
            "Authorization": "Bearer api-key",
        },
        json={
            "is_master": True,
            "fahrplan": {
                "conference": f"emf{event_year()}",
                "id": proposal.id,
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

    proposal = Proposal.query.get(proposal.id)
    assert proposal.youtube_url is None
