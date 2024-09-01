import pytest

from models.cfp import TalkProposal, Proposal


@pytest.fixture(scope="module")
def proposal(db, user):
    proposal = TalkProposal()
    proposal.title = "Title"
    proposal.description = "Description"
    proposal.user = user

    db.session.add(proposal)
    db.session.commit()

    return proposal


def test_denies_request_without_api_key(client, app, proposal):
    app.config.update(
        {
            "VIDEO_API_KEY": "api-key",
        }
    )

    rv = client.patch(
        f"/api/proposal/{proposal.id}",
        json={
            "youtube_url": "https://example.com/youtube.com",
            "thumbnail_url": "https://example.com/thumbnail",
            "c3voc_url": "https://example.com/media.ccc.de",
        },
    )
    assert rv.status_code == 401


def test_can_set_video_urls(client, app, proposal):
    app.config.update(
        {
            "VIDEO_API_KEY": "api-key",
        }
    )

    rv = client.patch(
        f"/api/proposal/{proposal.id}",
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

    proposal = Proposal.query.get(proposal.id)
    assert proposal.youtube_url == "https://example.com/youtube.com"
    assert proposal.thumbnail_url == "https://example.com/thumbnail"
    assert proposal.c3voc_url == "https://example.com/media.ccc.de"


def test_clearing_video_url(client, app, db, proposal):
    app.config.update(
        {
            "VIDEO_API_KEY": "api-key",
        }
    )

    proposal.youtube_url = "https://example.com/youtube.com"
    db.session.add(proposal)
    db.session.commit()

    rv = client.patch(
        f"/api/proposal/{proposal.id}",
        json={
            "youtube_url": None,
        },
        headers={
            "Authorization": "Bearer api-key",
        },
    )
    assert rv.status_code == 200

    proposal = Proposal.query.get(proposal.id)
    assert proposal.youtube_url is None


def test_rejects_disallowed_attributes(client, app, proposal):
    app.config.update(
        {
            "VIDEO_API_KEY": "api-key",
        }
    )

    rv = client.patch(
        f"/api/proposal/{proposal.id}",
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
