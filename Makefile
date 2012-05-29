run:
	SETTINGS_FILE=./config/development.cfg ./env/bin/python ./main.py

tickets:
	SETTINGS_FILE=./config/development.cfg ./env/bin/python ./utils.py createtickets

update:
	./env/bin/pip install -r ./requirements.txt

init:
	virtualenv ./env

reconcile:
	SETTINGS_FILE=./config/development.cfg ./env/bin/python ./utils.py reconcile -f tests/account.ofx
