This is the www.emfcamp.org web site

Requirements
=======

* [Python 2.7](https://www.python.org/downloads/)
* [Pip](https://pip.pypa.io/en/latest/installing.html)
* [VirtualEnv](https://virtualenv.pypa.io/en/latest/installation.html)
* [SQLite3](https://www.sqlite.org/download.html)


Starting
========
```
sudo apt-get install -y python-dev python-virtualenv libxml2-dev libxslt1-dev libffi-dev postgresql-server-dev-9.4 git
make init
make update # may take a few minutes if you don't have cached .whl files
make data
```

Alt method using 'easy\_install'
=======
To set up easy\_install go [here](https://pythonhosted.org/setuptools/easy_install.html#installing-easy-install "pythonhosted.org")
```
sudo easy_install virtualenv
make init
```

Using vagrant
=======

```
vagrant up
vagrant ssh
cd /vagrant
```
This is running all the necassary provisioning steps (see ```provision.sh```), only the final ```make``` and
```make admin``` is needed. Port 5000 is forwarded.

Running
=======
```
make update
make data
make
```

Now create a user (go to [http://localhost:5000/signup](http://localhost:5000/signup)) and then run:

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

Viewing
=======
The site will run on [http://localhost:5000](http://localhost:5000).

If you would like to change the port that the site uses you can set this in main.py (last line):

```python
    app.run(processes=2, port=8888)
```

You can also use this to make the site accessible outside of your computer.
Only do this if you're sure you know what you're doing.

```python
    app.run(processes=2, host="0.0.0.0")
```


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

