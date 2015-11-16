ifeq ("$(SETTINGS)", "")
	ifeq ("$(wildcard ./config/live.cfg)", "")
		SETTINGS=./config/development.cfg
	else
		SETTINGS=./config/live.cfg
	endif
endif

ifeq ("$(VIRTUAL_ENV)", "")
  ENV=. env/bin/activate;
endif

run:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./main.py

init:
	virtualenv --clear ./env

update:
	$(ENV) pip install --upgrade pip wheel setuptools
	$(ENV) pip install ndg-httpsclient
	$(ENV) pip install -r ./requirements.txt

outdated:
	$(ENV) pip list --outdated

listdepends:
	$(ENV) pip list|cut -d\  -f1|while read x; do echo $$x $$(pip show $$x|grep Requires); done

clean:
	rm -rf ./env


db:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py createdb

data: db tickets bankaccounts tokens

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
	$(ENV) SETTINGS_FILE=./config/test.cfg flake8 ./models ./views ./utils.py --ignore=E501,E302,W391,E201,E202,E127,E128,E151,E261,E303,E124
	$(ENV) nosetests ./tests/

