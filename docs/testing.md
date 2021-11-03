[![CI Status](https://github.com/emfcamp/Website/workflows/CI/badge.svg)](https://github.com/emfcamp/Website/actions?query=workflow%3ACI)
[![Coverage Status](https://coveralls.io/repos/github/emfcamp/Website/badge.svg?branch=master)](https://coveralls.io/github/emfcamp/Website?branch=master)

#### Bank Transfer
These are manually resolved via scripts and the admin panel.

This is the easiest way to get unpaid tickets into the system, but there's currently no easy way to test reconciliation.

#### Wise
TODO

#### Stripe
This is the easiest method to "pay" for a ticket when you're developing. The details for a successful payment are:

- **email**: whatever you want
- **card number**: 4242 4242 4242 4242
- **expiry**: anything in the future, e.g. 12/34
- **cvc**: anything, e.g. 123

If you want to test specific modes please check [their documentation](https://stripe.com/docs/testing 'Stripe testing docs')

Test users
==========

Create test users with:

```./flask dev cfp_data```

and enable `BYPASS_LOGIN` in config. You can then log in using, e.g. `/login/admin@test.invalid` and navigate to `/admin/`.

