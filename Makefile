run:
	./env/bin/python ./main.py

update:
	pip install -r ./requirements.txt

init:
	virtualenv ./env
