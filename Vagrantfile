# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure("2") do |config|
  config.vm.box = "debian/jessie64"
  # NB: versions of this box > 8.2.0 have kindly removed the virtualbox guest additions
  # because they're non-free. This breaks shared folders and some networking.
  # TODO: find a better box.
  config.vm.box_version = "8.2.0"
  config.vm.network "forwarded_port", guest: 5000, host: 5000
  config.vm.network "private_network", type: "dhcp"
  config.vm.synced_folder ".", "/vagrant", type: "nfs"
  config.vm.provision "shell", path: "provision.sh"
end
