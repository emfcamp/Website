Development
===========

If you want to get involved, the best way to get started is to join us
on IRC, on ``#emfcamp-web`` on ``irc.libera.chat``.

.. raw:: html

    <p>Join with IRCCloud:
    <a href="https://www.irccloud.com/invite?channel=%23emfcamp-web&amp;hostname=irc.libera.chat&amp;port=6697&amp;ssl=1" target="_blank">
        <img src="https://www.irccloud.com/invite-svg?channel=%23emfcamp-web&amp;hostname=irc.libera.chat&amp;port=6697&amp;ssl=1" height="18">
    </a></p>

Please ask the team before starting to work on a feature -- while we try to keep the Github issues
up to date, there's often a bit more context or some dependencies which we've forgotten to add.
We don't want you to waste your time!

Getting started
---------------

The quick summary:

1. Make sure you have Git and Docker installed
2. Check out the website repository: ``git clone https://github.com/emfcamp/Website.git``
3. Start the development environment: ``docker compose up``
4. Load the website at http://localhost:2342

Once you've finished making your changes:

1. Run the tests and check they pass: ``./run_tests``
2. Commit and push your change


We also recommend you have ``uv`` `installed on your development
machine <https://docs.astral.sh/uv/getting-started/installation/>`__, as
it’s sometimes useful to use this command outside Docker.

To stop all containers, use ``docker compose stop``. To delete all data
and start over fresh, you can use ``docker compose down``.

Management commands can be listed and run using the ``./flask`` command,
which forwards them to the flask command line within the container.

IDE Tips
--------

If you use Visual Studio Code or Zed, it should present you with the
option to open the project in a dev container. If not, run ``code .``
from your local copy, and ensure you have the `Dev Containers
extension <https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers>`__
installed.

Reopening in a dev container will start everything via Docker, attach
your VSCode instance to the application container, install relevant
extensions, and ensure everything is configured to fit with our
standards.

The first time you start the dev container you will need to tell VSCode
where to find the ``uv`` virtual environment. You can do this by open
the command palette (Cmd-P on macOS devices) and searching for “Python:
Select interpreter”, the list presented should include
``website-${randomHash}-py3.11``, which will be annotated as “uv”.
Select that, and then any Python tooling and shells will run within the
appropriate virtualenv.


Errors starting the dev server
------------------------------

e.g. ``Error: While importing 'dev_server', an ImportError was raised.``

If you’ve just updated and you’re seeing errors when starting the dev
server, first make sure you try:

::

       docker compose up --build

Code Style
----------

For Python, we currently use `Ruff <https://docs.astral.sh/ruff/>`__ to
enforce code style. These checks are run by ``./run_tests``.

However, it’s easy to forget these checks, so you can also run them as a
git pre-commit hook using `pre-commit <https://pre-commit.com/>`__. To
set this up on the host where you’ll be using git:

::

   uvx pre-commit install

Adding accounts
---------------

Once you’ve created an account on the website, you can use
``./flask make_admin`` to make your user an administrator. Or, you can
create an account and simultaneously make it an admin by using
``./flask make_admin -e email@domain.tld``

E-mail sending is disabled in development (but is printed out on the
console). You can also log in directly by setting ``BYPASS_LOGIN=True``
in ``config/development.cfg`` and then using a URL of the form
e.g. ``/login/admin@test.invalid``.

Database Migrations
-------------------

- ``./flask db migrate -m 'Migration name'`` to generate migration
  scripts when models have been updated.
- ``./flask db upgrade`` to run any migration scripts you’ve generated
  (or populate a fresh DB).
- ``./flask db downgrade`` to undo the last migration.

For more migration commands, see the `flask-migrate
docs <https://flask-migrate.readthedocs.io/en/latest/>`__.
