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
SQLALCHEMY_DATABASE_URI = "postgresql://postgres@postgres/emf_site
```

and then run:

```
docker-compose pull postgres
docker-compose restart postgres
```

