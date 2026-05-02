Upgrading Python
================

* Increment version specifier in ``pyproject.toml``
* Update the source container version in ``./docker/Dockerfile.base``
* Rebuild base Docker image: ``docker build -f ./docker/Dockerfile.base -t ghcr.io/emfcamp/website-base:latest .``
* Rebuild base-dev Docker image: ``docker build -f ./docker/Dockerfile.base-dev -t ghcr.io/emfcamp/website-base-dev:latest .``
* ``docker compose up --build``

Now you can ``./run_tests`` and check if everything worked successfully.

Deploying the update
--------------------

This is a bit ugly due to the way we handle the base containers.

* Commit and push your changes directly to ``main``. (Tests will fail in a PR.)
* Cancel the ``deploy`` workflow build (or it'll just fail anyway)
* Wait for the ``base`` workflow to finish building (takes a while)
* Re-trigger the ``deploy`` workflow from the GitHub UI
