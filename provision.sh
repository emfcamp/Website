cd /vagrant
sudo apt-get update
sudo apt-get install -y python-dev python-virtualenv libxml2-dev libxslt1-dev libffi-dev postgresql-server-dev-9.4 git
touch .inside-vagrant
make init
make update
make data

cat > /home/vagrant/.bash_profile <<EOF
cd /vagrant
. ./env/bin/activate
EOF
