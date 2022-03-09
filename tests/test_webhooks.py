import os


def load_webhook_fixture(name):
    fixture_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "webhook_fixtures", f"{name}.json"
    )
    with open(fixture_path, "r") as f:
        return f.read().strip()


def load_webhook_signature(name):
    fixture_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "webhook_fixtures", f"{name}.sig"
    )
    with open(fixture_path, "r") as f:
        return f.read().strip()


def test_wise_webhook(client):
    url = "/wise-webhook"
    payload = load_webhook_fixture("balances#credit")
    signature = load_webhook_signature("balances#credit")
    response = client.post(
        path=url,
        headers={
            "Content-Type": "application/json",
            "X-Signature-SHA256": signature,
        },
        data=payload,
        follow_redirects=True,
    )
    assert response.status_code == 204
