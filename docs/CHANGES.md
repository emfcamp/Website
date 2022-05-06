2022-03-17
==========

Flask-Mail has been replaced with Flask-Mailman, add the following to your config:

```
MAIL_BACKEND = "console"
```

and delete references to:

```
MAIL_SUPPRESS_SEND
```

For an example of production-like config, see `config/kelvin.cfg`.

2022-02-07
==========

Flask-Caching has been updated, change your config:

```
CACHE_TYPE = "flask_caching.backends.SimpleCache"
```

2022-02-04
==========

* Flask version has been updated - you may need to run `docker compose up --build` in your dev environment.
* Black version is now 22.1.0 - if your editor auto-formats you might have to update your local version.

2022-01-12
==========

We can now attempt to reconcile inside the Wise webhook. Turn it on with the following feature flag:

```
RECONCILE_IN_WEBHOOK = True
```

2022-01-07
==========

- We've moved from `master` to `main`. See above for instructions to fix your local repo.
- The dev port has moved to `:2342` instead of `:5000`.
- We're using `docker compose` instead of `docker-compose`. Please update your docker and scripts.
- We're now using Wise for bank transfers, because we can get webhooks and immediate statements. See `docs/wise.md` for instructions.

If you're not testing Wise, make sure you've copied across these config items from the example:

```
TRANSFERWISE_ENVIRONMENT
TRANSFERWISE_API_TOKEN
```

2021-11-03
==========

GoCardless has been removed. Delete references to GOCARDLESS in your config files:

```
GOCARDLESS_ENVIRONMENT
GOCARDLESS_ACCESS_TOKEN
GOCARDLESS_WEBHOOK_SECRET
GOCARDLESS
GOCARDLESS_EURO
EXPIRY_DAYS_GOCARDLESS
```

This includes database changes, so remember to run `./flask db upgrade`

CSRF protection has also been removed. Delete references to WTF_CSRF in your config files:

```
WTF_CSRF_TIME_LIMIT
WTF_CSRF_SSL_STRICT
WTF_CSRF_ENABLED
```

2021-09-27
==========

We'll shortly rename the `master` branch to `main`. When this happens, you'll get the following error:

```
Your configuration specifies to merge with the ref 'refs/heads/master' from the remote, but no such ref was fetched.
```

To fix it, run this:

```
git branch -m master main
git branch -u origin/main main
git remote set-head origin -a
git fetch origin --prune
```

2021-09-10
==========

Postgres has been updated. Modify your `development.cfg` to contain:

```
SQLALCHEMY_DATABASE_URI = "postgresql://postgres:postgres@postgres/emf_site
```

and then run:

```
docker-compose pull postgres
docker-compose down postgres
docker-compose up -d
```
