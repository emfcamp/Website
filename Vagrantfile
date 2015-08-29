# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure("2") do |config|
  config.vm.box = "debian8"
  config.vm.box_url = "https://f458271790152e424d62-0ee3ea466698a63342545f1433b44e51.ssl.cf3.rackcdn.com/debian8.box"

  config.vm.network "forwarded_port", guest: 5000, host: 5000

  config.vm.provision "shell", path: "provision.sh"
end
