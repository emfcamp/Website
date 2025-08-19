import pytest

from models import event_year
from models.cfp import Proposal, TalkProposal


@pytest.fixture
def proposal(db, user):
    # Setup
    proposal = TalkProposal(
        title="Title",
        description="Description",
        user=user,
    )

    db.session.add(proposal)
    db.session.commit()

    # Fixture lifetime
    yield proposal

    # Teardown
    db.session.delete(proposal)
    db.session.commit()


@pytest.fixture
def valid_auth_headers():
    return {"Authorization": "Bearer video-api-test-token"}


def test_denies_request_without_api_key(client, app, proposal):
    rv = client.post(
        "/api/proposal/c3voc-publishing-webhook",
        json={
            "is_master": True,
            "fahrplan": {
                "conference": "emf1970",
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
    assert rv.status_code == 401


def test_denies_request_no_master(client, app, proposal, valid_auth_headers):
    rv = client.post(
        "/api/proposal/c3voc-publishing-webhook",
        headers=valid_auth_headers,
        json={
            "is_master": False,
            "fahrplan": {
                "conference": "emf1970",
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
    assert rv.status_code == 403


def test_denies_request_wrong_year(client, app, proposal, valid_auth_headers):
    rv = client.post(
        "/api/proposal/c3voc-publishing-webhook",
        headers=valid_auth_headers,
        json={
            "is_master": True,
            "fahrplan": {
                "conference": "emf1970",
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
    assert rv.status_code == 422


def test_request_none_unchanged(client, app, db, proposal, valid_auth_headers):
    rv = client.post(
        "/api/proposal/c3voc-publishing-webhook",
        headers=valid_auth_headers,
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


def test_update_voctoweb_with_correct_url(client, app, db, proposal, valid_auth_headers):
    proposal.video_recording_lost = True
    db.session.add(proposal)
    db.session.commit()

    rv = client.post(
        "/api/proposal/c3voc-publishing-webhook",
        headers=valid_auth_headers,
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
    assert proposal.video_recording_lost is False
    assert proposal.youtube_url is None


def test_denies_voctoweb_with_wrong_url(client, app, db, proposal, valid_auth_headers):
    proposal.c3voc_url = "https://example.com"
    proposal.video_recording_lost = True
    db.session.add(proposal)
    db.session.commit()

    rv = client.post(
        "/api/proposal/c3voc-publishing-webhook",
        headers=valid_auth_headers,
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
    # setup sets this to true, the api should not change that
    assert proposal.video_recording_lost is True
    assert proposal.c3voc_url == "https://example.com"


def test_clears_voctoweb(client, app, db, proposal, valid_auth_headers):
    proposal.c3voc_url = "https://example.com"
    db.session.add(proposal)
    db.session.commit()

    rv = client.post(
        "/api/proposal/c3voc-publishing-webhook",
        headers=valid_auth_headers,
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


def test_update_thumbnail_with_path(client, app, db, proposal, valid_auth_headers):
    rv = client.post(
        "/api/proposal/c3voc-publishing-webhook",
        headers=valid_auth_headers,
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
    assert proposal.thumbnail_url == "https://static.media.ccc.de/media/thumb.jpg"
    assert proposal.c3voc_url is None
    assert proposal.youtube_url is None


def test_update_thumbnail_with_url(client, app, db, proposal, valid_auth_headers):
    rv = client.post(
        "/api/proposal/c3voc-publishing-webhook",
        headers=valid_auth_headers,
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
    assert proposal.thumbnail_url == "https://example.com/thumb.jpg"
    assert proposal.c3voc_url is None
    assert proposal.youtube_url is None


def test_denies_thumbnail_not_url(client, app, db, proposal, valid_auth_headers):
    proposal.thumbnail_url = "https://example.com/thumb.jpg"
    db.session.add(proposal)
    db.session.commit()

    rv = client.post(
        "/api/proposal/c3voc-publishing-webhook",
        headers=valid_auth_headers,
        json={
            "is_master": True,
            "fahrplan": {
                "conference": f"emf{event_year()}",
                "id": proposal.id,
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

    proposal = Proposal.query.get(proposal.id)
    assert proposal.thumbnail_url == "https://example.com/thumb.jpg"


def test_clears_thumbnail(client, app, db, proposal, valid_auth_headers):
    proposal.thumbnail_url = "https://example.com/thumb.jpg"
    db.session.add(proposal)
    db.session.commit()

    rv = client.post(
        "/api/proposal/c3voc-publishing-webhook",
        headers=valid_auth_headers,
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


def test_update_from_youtube_with_correct_url(client, app, db, proposal, valid_auth_headers):
    proposal.video_recording_lost = True
    db.session.add(proposal)
    db.session.commit()

    rv = client.post(
        "/api/proposal/c3voc-publishing-webhook",
        headers=valid_auth_headers,
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
    assert proposal.video_recording_lost is False
    assert proposal.youtube_url == "https://www.youtube.com/watch"


def test_denies_youtube_update_with_existing_url(client, app, db, proposal, valid_auth_headers):
    proposal.youtube_url = "https://example.com"
    proposal.video_recording_lost = True
    db.session.add(proposal)
    db.session.commit()

    rv = client.post(
        "/api/proposal/c3voc-publishing-webhook",
        headers=valid_auth_headers,
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
    # setup sets this to true, the api should not change that
    assert proposal.video_recording_lost is True
    assert proposal.youtube_url == "https://example.com"


def test_denies_youtube_update_with_wrong_url(client, app, db, proposal, valid_auth_headers):
    proposal.youtube_url = "https://example.com"
    proposal.video_recording_lost = True
    db.session.add(proposal)
    db.session.commit()

    rv = client.post(
        "/api/proposal/c3voc-publishing-webhook",
        headers=valid_auth_headers,
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
    # setup sets this to true, the api should not change that
    assert proposal.video_recording_lost is True
    assert proposal.youtube_url == "https://example.com"


def test_clears_youtube(client, app, db, proposal, valid_auth_headers):
    proposal.youtube_url = "https://example.com"
    db.session.add(proposal)
    db.session.commit()

    rv = client.post(
        "/api/proposal/c3voc-publishing-webhook",
        headers=valid_auth_headers,
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
