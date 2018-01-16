This is the www.emfcamp.org web site, built with Flask & Postgres by the 
EMF web team.

[![Build Status](https://travis-ci.org/emfcamp/Website.svg?branch=master)](https://travis-ci.org/emfcamp/Website)

Get Involved
============

If you want to get involved, the best way is to join us on IRC, on #emfcamp-web on chat.freenode.net.

Join with IRCCloud: <a href="https://www.irccloud.com/invite?channel=%23emfcamp-web&amp;hostname=irc.freenode.net&amp;port=6697&amp;ssl=1" target="_blank"><img src="https://www.irccloud.com/invite-svg?channel=%23emfcamp-web&amp;hostname=irc.freenode.net&amp;port=6697&amp;ssl=1" height="18"></a>

Getting Started
=======

Install [Vagrant](https://www.vagrantup.com/) and
[VirtualBox](https://www.virtualbox.org/).

```
vagrant up --provider virtualbox
vagrant ssh
make data
make
```
This is running all the necassary provisioning steps (see
```provision.sh```). Port 5000 is forwarded, so you should be able to
view your development server on http://localhost:5000.

Once you've created an account, you can use `make admin` to make your user an administrator.

If you want to clean out the database and start again then:

```
rm var/development.db
make update
make data
```

Payments for tickets
====================
We have (currently) three payment systems: bank transfer, Stripe and GoCardless.

#### Bank Transfer
These are manually resolved via scripts and the admin panel.

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

```make users````

and enable `BYPASS_LOGIN` in config. You can then log in using, e.g. `/login/admin@test.invalid` and navigate to `/admin/`.


Links to Documentation
======================

N.B. the version might be wrong for some of these, check against requirements.txt

## Flask

* [Flask](http://flask.pocoo.org/docs/)
* [Flask-Script](http://packages.python.org/Flask-Script/)

## Templates

* [Jinja2](http://jinja.pocoo.org/docs/)
* [Bootstrap](http://twitter.github.com/bootstrap/)

## Forms

* [Flask-WTF](http://packages.python.org/Flask-WTF/)
* [WTForms](http://wtforms.readthedocs.org/en/latest/)

## Database

* [Flask-SQLAlchemy](http://packages.python.org/Flask-SQLAlchemy/)

