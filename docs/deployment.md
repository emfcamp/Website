Development hints
=================

We have just upgraded to python3, so there may be bits of code or stylistic choices that only make sense in python2.7

We've also recently changed Ticket to Purchase, and TicketType to Product.
There may still be bits of old code that refer to these classes or use confusing names. Please fix them if you see them!

Depending on your setup, you may want to run the following to avoid accidentally committing things:

```
git update-index --skip-worktree config/test.cfg
```

To undo this (if either file has been updated by someone else, or you want to commit your changes):

```
git update-index --no-skip-worktree config/test.cfg
```

Development processes
=====================

We're always open to pull requests (where you fork the repo in Github and ask us to merge back your changes). However, it's a good idea to discuss the change on IRC before starting work.

Once tickets are on sale, people with access to the repo should keep any new development to feature branches. We try to merge to master frequently, so hide anything accessible to visitors behind config. Bugfixes will usually be done on master.

We test all branches with Travis - you can run `make test` locally to run these tests during development.


Code style
==========

We generally follow [PEP8](https://www.python.org/dev/peps/pep-0008/). Flake will
pick up obvious violations of this style, so please listen to it. Beyond that, we're
not dogmatic about style as long as it's readable, but you may find your code
tidied up in a later commit if it's messy or follows an anti-pattern.

 - lines can be longer than 79 characters if it makes sense
 - splitting a line into multiple steps is usually better than using backslashes
 - formatting SQLAlchemy queries cleanly is difficult, so conventions are more relaxed
 - Prometheus metrics aren't constant, so don't UPPERCASE them

Always end multi-line lists in a comma. This makes git diffs work more cleanly.
If you're used to JavaScript/JSON, Python will not do what you expect with:
```
toys = [
    'top',
    'hoop'
    'ball',
    'balloon'
]
```

Tuples are specifically for strongly ordered data, e.g. `return (x, y)`.
Prefer list `['a', 'b']` or set `{'a', 'b'}` literals where appropriate.
If you're used to SQL, Python will not do what you expect with:
```
if toy in ('balloon'):
```

We do follow the convention of splitting imports into built-ins, third-party packages,
and local application modules, but don't worry too much about getting it right.


