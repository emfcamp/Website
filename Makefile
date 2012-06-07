

# find out which machine we are on
# and use the right settings file.
hostname=$(shell hostname)
SETTINGS=./config/development.cfg
OFX=tests/account.ofx

#
# jasper is using postgres on his server
# (actual config not in git cos of passwords)
#
ifeq ($(hostname),monstrosity)
SETTINGS=./config/live.cfg
endif

#
# the live site, also not in git cos of passwords.
#
ifeq ($(hostname),gauss)
SETTINGS=/etc/emf-site.cfg
# live reconcile data
OFX=~russ/data.ofx
endif

run:
	SETTINGS_FILE=$(SETTINGS) ./env/bin/python ./main.py

tickets:
	SETTINGS_FILE=$(SETTINGS) ./env/bin/python ./utils.py createtickets

update:
	./env/bin/pip install -r ./requirements.txt

init:
	virtualenv ./env

checkreconcile:
	SETTINGS_FILE=$(SETTINGS) ./env/bin/python ./utils.py reconcile -f $(OFX)

reallyreconcile:
	SETTINGS_FILE=$(SETTINGS) ./env/bin/python ./utils.py reconcile -d -f $(OFX)

shell:
	SETTINGS_FILE=$(SETTINGS) ./env/bin/python ./utils.py shell

test:
	SETTINGS_FILE=$(SETTINGS) ./env/bin/python ./utils.py testemails
