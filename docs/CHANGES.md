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

