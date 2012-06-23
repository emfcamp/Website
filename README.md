This is the www.emfcamp.org web site

Starting
========
```
sudo apt-get install python-dev python-virtualenv
make init
make update
make tickets
```

Running
=======
```
make update
make
```

If you want the site to be accessible by the rest of the world then change app.run() at the end of main.py to app.run(host="0.0.0.0")
