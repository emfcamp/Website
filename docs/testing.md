[![Build Status](https://travis-ci.org/emfcamp/Website.svg?branch=master)](https://travis-ci.org/emfcamp/Website)

#### Bank Transfer
These are manually resolved via scripts and the admin panel. There's currently no easy way to test reconciliation.

#### Stripe
This is the easiest method to "pay" for a ticket when you're developing. The details for a successful payment are:

- **email**: whatever you want
- **card number**: 4242 4242 4242 4242
- **expiry**: anything in the future, e.g. 12/34
- **cvc**: anything, e.g. 123

If you want to test specific modes please check [their documentation](https://stripe.com/docs/testing 'Stripe testing docs')

#### GoCardless
Unfortunately GoCardless don't offer a simple method of setting up a developer system. If you want to test this payment method you'll have to:

1. Make a copy of 'config/development.cfg' and name it 'config/live.cfg'
2. Set up your own merchant account (go to [https://gocardless.com/merchants/new](https://gocardless.com/merchants/new)).
3. Enable Sandbox mode (button at the top right)
4. Enable developer mode: 'More...' (top left) > Developer (this should take you straight to the [API Keys](https://dashboard-sandbox.gocardless.com/developer/api-keys)). 
5. Copy the following values from the API Keys to the appropriate environment variable in 'live.cfg':
    - 'App Identifier' -> `GOCARDLESS_APP_ID`
    - 'App secrets' -> `GOCARDLESS_APP_SECRET`
    - 'Merchant access token' -> `GOCARDLESS_ACCESS_TOKEN`
    - 'Merchant id' -> `GOCARDLESS_MERCHANT_ID`
6. From Developer go to [URI Settings](https://dashboard-sandbox.gocardless.com/developer/uri-settings) (left hand menu block)
7. Set the following:
    - **Redirect URI**: `http://localhost:5000/pay/gocardless/`
    - **Cancel URI**: `http://localhost:5000/pay/gocardless/`

In theory you should now be able to use GoCardless to checkout. You should see the payments under [payments](https://dashboard-sandbox.gocardless.com/payments) (top left)

To create a successful Direct Debit in the sandbox, use:
- **sort code**: 20-00-00
- **account number**: 55779911
- **postcode**: any valid postcode, e.g. SW1A 1AA
- **city**: any value

Test users
==========

Create three test users with:

```make users```

and enable `BYPASS_LOGIN` in config. You can then log in using, e.g. `/login/admin@test.invalid` and navigate to `/admin/`.

