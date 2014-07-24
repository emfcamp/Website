This is the www.emfcamp.org web site

Starting
========
```
sudo apt-get install python-dev python-virtualenv libxml2-dev libxslt-dev postgresql-server-dev-9.1
make init
make update
make data
```

Alt method using 'easy\_install'
=======
To set up easy\_install go [here](http://packages.python.org/distribute/easy_install.html#installing-easy-install "packages.python.org")
```
sudo easy_install virtualenv
make init
```

Running
=======
```
make update
make data
make
```

Now create a user ("signup") and then run:

```
make admin
```

This will make your user an administrator.

If you want to clean out the database and start again then:

```
rm var/test.db
make update
make data
```

If you want the site to be accessible by the rest of the world then change app.run() at the end of main.py to app.run(host="0.0.0.0")

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
* [WTForms](http://wtforms.simplecodes.com/docs/1.0.1/)

## Database

* [Flask-SQLAlchemy](http://packages.python.org/Flask-SQLAlchemy/)

