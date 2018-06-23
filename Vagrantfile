# -*- mode: ruby -*-
# vi: set ft=ruby :

sharing = 'nfs'
if ENV['VAGRANT_SMB']
  sharing = 'smb'
end

Vagrant.configure("2") do |config|
  config.vm.box = "debian/contrib-stretch64"
  config.vm.network "forwarded_port", guest: 5000, host: 5000
  config.vm.network "private_network", ip: "172.16.63.2"
  config.vm.synced_folder ".", "/vagrant", type: sharing
  config.vm.provision "shell", path: "provision.sh"
end
