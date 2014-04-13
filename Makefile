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



db: tickets tokens shifts

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

