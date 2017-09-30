cd /vagrant
sudo apt-get update
sudo apt-get install -y python3-dev python-virtualenv libxml2-dev libxslt1-dev libffi-dev postgresql-server-dev-9.6 postgresql-9.6 git glpk-utils

cat > /etc/postgresql/9.6/main/pg_hba.conf <<EOF
# TYPE  DATABASE        USER            ADDRESS                 METHOD
local   all             postgres                                peer
local   all             vagrant                                 trust
host    all             vagrant         127.0.0.1/32            trust
host    all             vagrant         ::1/128                 trust
local   all             all                                     peer
host    all             all             127.0.0.1/32            md5
host    all             all             ::1/128                 md5
EOF

pg_ctlcluster 9.6 main reload
su postgres -c 'createuser -s vagrant'
su postgres -c 'createdb -O vagrant emf_site'
su postgres -c 'createdb -O vagrant emf_site_test'

touch .inside-vagrant
make clean
make init
make update
make data

cat > /home/vagrant/.bash_profile <<EOF
cd /vagrant
. ./env/bin/activate
EOF
