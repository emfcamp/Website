# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure("2") do |config|
  config.vm.box = "debian/jessie64"
  config.vm.box_version = "8.2.0"
  config.vm.network "forwarded_port", guest: 5000, host: 5000
  config.vm.network "private_network", type: "dhcp"
  config.vm.synced_folder ".", "/vagrant", type: "nfs"
  config.vm.provision "shell", path: "provision.sh"
end
