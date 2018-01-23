This is the www.emfcamp.org web site, built with Flask & Postgres by the 
EMF web team.

[![Build Status](https://travis-ci.org/emfcamp/Website.svg?branch=master)](https://travis-ci.org/emfcamp/Website)

Get Involved
============

If you want to get involved, the best way is to join us on IRC, on #emfcamp-web on chat.freenode.net.

Join with IRCCloud: <a href="https://www.irccloud.com/invite?channel=%23emfcamp-web&amp;hostname=irc.freenode.net&amp;port=6697&amp;ssl=1" target="_blank"><img src="https://www.irccloud.com/invite-svg?channel=%23emfcamp-web&amp;hostname=irc.freenode.net&amp;port=6697&amp;ssl=1" height="18"></a>

Getting Started
===============

The easiest way is to install [Vagrant](https://www.vagrantup.com/) and
[VirtualBox](https://www.virtualbox.org/).

```
vagrant up --provider virtualbox
vagrant ssh
```

This installs the necessary packages and dependencies for you. Then run:

```
make update
make data
make
```
You should then be able to view your development server on http://localhost:5000.

Once you've created an account, you can use `make admin` to make your user an administrator.

For more, see:

* [Documentation](docs/documentation.md)
* [Testing](docs/testing.md)
* [Deployment](docs/deployment.md)
* [Contributing](.github/CONTRIBUTING.md)

