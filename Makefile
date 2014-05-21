ifeq ("$(wildcard ./config/live.cfg)", "")
	SETTINGS=./config/development.cfg
else
	SETTINGS=./config/live.cfg
endif

run:
	SETTINGS_FILE=$(SETTINGS) ./env/bin/python ./main.py

init:
	virtualenv ./env

update:
	./env/bin/python ./env/bin/pip install -r ./requirements.txt

clean:
	rm -rf .env


db:
	SETTINGS_FILE=$(SETTINGS) ./env/bin/python ./utils.py createdb

data: tickets tokens shifts

tickets:
	SETTINGS_FILE=$(SETTINGS) ./env/bin/python ./utils.py createtickets

tokens:
	SETTINGS_FILE=$(SETTINGS) ./env/bin/python ./utils.py addtokens

shifts:
	SETTINGS_FILE=$(SETTINGS) ./env/bin/python ./utils.py createroles
	SETTINGS_FILE=$(SETTINGS) ./env/bin/python ./utils.py createshifts


checkreconcile:
	SETTINGS_FILE=$(SETTINGS) ./env/bin/python ./utils.py reconcile

reallyreconcile:
	SETTINGS_FILE=$(SETTINGS) ./env/bin/python ./utils.py reconcile -d


warnexpire:
	SETTINGS_FILE=$(SETTINGS) ./env/bin/python ./utils.py warnexpire

expire:
	SETTINGS_FILE=$(SETTINGS) ./env/bin/python ./utils.py expire


shell:
	SETTINGS_FILE=$(SETTINGS) ./env/bin/python ./utils.py shell

testemails:
	SETTINGS_FILE=$(SETTINGS) ./env/bin/python ./utils.py testemails

admin:
	SETTINGS_FILE=$(SETTINGS) ./env/bin/python ./utils.py makeadmin

test:
	SETTINGS_FILE=./config/test.cfg flake8 ./models ./views --ignore=E501,F403,E302,F401,E128,W293,W391,E251,E303,E502,E111,E225,E221,W291,E124,W191,E101,E201,E202,E261,E127,E265,E231
	SETTINGS_FILE=./config/test.cfg nosetests ./models ./views
