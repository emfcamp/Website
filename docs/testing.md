[![CI Status](https://github.com/emfcamp/Website/workflows/CI/badge.svg)](https://github.com/emfcamp/Website/actions?query=workflow%3ACI)
[![Coverage Status](https://coveralls.io/repos/github/emfcamp/Website/badge.svg?branch=main)](https://coveralls.io/github/emfcamp/Website?branch=main)

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
2. Configure a sandbox environment
3. Set `STRIPE_SECRET_KEY` & `STRIPE_PUBLIC_KEY` using these keys from this environment
4. Install the Stripe CLI `brew install stripe/stripe-cli/stripe`
5. `stripe login`
6. `stripe listen --forward-to localhost:2342/stripe-webhook` (leave it running)
7. set `STRIPE_WEBHOOK_KEY` to the value returned from the previous (will start `whsec_`)
8. you should be able to 'buy' tickets using [test cards](https://docs.stripe.com/testing#cards)
9. the `stripe listen` terminal should show successful webhook calls

Test users
==========

Create test users with:

```./flask dev cfp_data```

and enable `BYPASS_LOGIN` in config. You can then log in using, e.g. `/login/admin@test.invalid` and navigate to `/admin/`.

