[![CI Status](https://github.com/emfcamp/Website/workflows/CI/badge.svg)](https://github.com/emfcamp/Website/actions?query=workflow%3ACI)
[![Coverage Status](https://coveralls.io/repos/github/emfcamp/Website/badge.svg?branch=main)](https://coveralls.io/github/emfcamp/Website?branch=main)

## Bank Transfer
These are manually resolved via scripts and the admin panel.

This is the easiest way to get unpaid tickets into the system, but there's currently no easy way to test reconciliation.

## Wise
This can only be tested with their live environment. See `docs/wise.md` for details.

## Stripe
This is the easiest method to "pay" for a ticket when you're developing. The details for a successful payment are:

- **email**: whatever you want
- **card number**: 4242 4242 4242 4242
- **expiry**: anything in the future, e.g. 12/34
- **cvc**: anything, e.g. 123

If you want to test specific modes please check [their documentation](https://stripe.com/docs/testing 'Stripe testing docs')

### Setting it up test stripe


1. Sign up for stripe. You can skip/cancel through without giving bank details
2. Get the secret & public api keys https://dashboard.stripe.com/test/apikeys
3. Set `STRIPE_SECRET_KEY` & `STRIPE_PUBLIC_KEY` using these keys
4. install stripe cli `brew install stripe/stripe-cli/stripe`
5. `stripe login`

#### If the stripe api version is not the latest

1. Get an [ngrok.com](https://ngrok.com) account
2. install the ngrok client (`brew install ngrok/ngrok/ngrok`)
3. `ngrok ngrok config add-authtoken <some token>` (the ngrok dashboard should show the token)
4. `ngrok http http://localhost:2342` this should show the ngrok forwarding domain for you (something like https://d5a7-329-22-333-28.ngrok-free.app)
5. `stripe webhook_endpoints create --url https://d5f7-149-22-218-28.ngrok-free.app/stripe-webhook --api-version 2020-08-27 --enabled-events '*'`

#### If the stripe api version is latest

We are currently using version 2020-08-27 ignore this for no
1. `stripe listen --forward-to localhost:2342/stripe-webhook` (leave it running)
2. set `STRIPE_WEBHOOK_KEY` to the value returned from the previous (will start `whsec_`)
3. you should be able to 'buy' tickets using [test cards](https://docs.stripe.com/testing#cards)
4. the `stripe listen` terminal should show successful webhook calls

Test users
==========

Create test users with:

```./flask dev cfp_data```

and enable `BYPASS_LOGIN` in config. You can then log in using, e.g. `/login/admin@test.invalid` and navigate to `/admin/`.

