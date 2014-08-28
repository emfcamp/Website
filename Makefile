ifeq ("$(wildcard ./config/live.cfg)", "")
	SETTINGS=./config/development.cfg
else
	SETTINGS=./config/live.cfg
endif

ifeq ("$(VIRTUAL_ENV)", "")
  ENV=. env/bin/activate;
endif

run:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./main.py

init:
	virtualenv ./env

update:
	$(ENV) pip install -r ./requirements.txt --use-mirrors

clean:
	rm -rf ./env


db:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py createdb

data: db tickets bankaccounts

tickets:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py createtickets

tokens:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py createtokens

bankaccounts:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py createbankaccounts

loadofx:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py loadofx -f var/data.ofx
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py loadofx -f var/data-eur.ofx

checkreconcile:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py reconcile

reallyreconcile:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py reconcile -d

sendtickets:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py sendtickets


shell:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py shell

testemails:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py testemails

admin:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py makeadmin

arrivals:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py makearrivals

test:
	$(ENV) SETTINGS_FILE=./config/test.cfg flake8 ./models ./views ./utils.py --ignore=E501,F403,E302,E128,W293,W391,E251,E303,E502,E111,E225,E221,W291,E124,W191,E101,E201,E202,E261,E127,E265,E231

