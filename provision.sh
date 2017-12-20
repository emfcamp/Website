cd /vagrant
sudo apt-get update
sudo apt-get install -y python3-dev python-virtualenv libxml2-dev libxslt1-dev libffi-dev postgresql-server-dev-9.6 git glpk-utils
touch .inside-vagrant
make clean
make init
make update
make data

cat > /home/vagrant/.bash_profile <<EOF
cd /vagrant
. ./env/bin/activate
EOF
