from flask import current_app as app
import pytransferwise


def transferwise_validate():
    """ Validate that TransferWise is configured and operational"""
    result = []

    env = app.config.get("TRANSFERWISE_ENVIRONMENT")
    if env == "sandbox":
        result.append((True, "Sandbox environment being used"))
    elif env == "live":
        result.append((True, "Live environment being used"))
    else:
        result.append((False, "No environment configured"))

    val = app.config.get("TRANSFERWISE_API_TOKEN", "")
    if len(val) == 36:
        result.append((True, "Access token set"))
    else:
        result.append((False, "Access token not set"))

    try:
        client = pytransferwise.Client()
        user = client.users.me()
        result.append((True, f"Connection to TransferWise API succeeded"))
    except:
        result.append((False, f"Unable to connect to TransferWise: {e}"))

    profiles = client.profiles.list()
    business_profile = next(filter(lambda p: p.type == "business", profiles), None)
    if business_profile:
        result.append((True, "TransferWise business profile exists"))
    else:
        result.append((False, "TransferWise business profile does not exist"))

    webhooks = client.subscriptions.list(profile_id=business_profile.id)
    if webhooks:
        result.append((True, "Webhook event subscriptions are present"))
    else:
        result.append((False, "Webhook event subscriptions are not present"))

    return result
