This is the www.emfcamp.org web site

Starting
========
```
sudo apt-get install python-dev python-virtualenv
make init
make update
make tickets
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
make
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

