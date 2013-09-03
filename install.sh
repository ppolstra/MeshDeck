#! /bin/bash

# Install script for the MeshDeck addon to The Deck
# Initially created for a presentation at Blackhat EU 2013
#
# Author: Dr. Phil Polstra
#
# Public domain, no warranty, etc. etc.
#

# first check if you are root
if [ "$UID" != "0" ]; then
  echo "Ummm... you might want to run this script as root";
  exit 1
fi

# check to see if they have Python
command -v python >/dev/null 2>&1 || {
  echo "Sorry, but you need Python for this stuff to work";
  exit 1; }

# extract XBee Python module to /tmp then install
echo "Installing XBee Python module"
tar -xzf XBee-2.0.0.tar.gz -C /tmp || {
  echo "Could not install XBee module";
  exit 1; }

currdir=$PWD
cd /tmp/XBee-2.0.0
python setup.py install || {
  echo "XBee module install failed";
  exit 1; }
echo "XBee Python module successfully installed"

# setup the files
echo "Creating files in /usr/bin, /usr/sbin, and /etc/init.d"
cd $currdir
(cp meshdeck.py /usr/bin/MeshDeck.py && chmod 744 /usr/bin/MeshDeck.py) || {
  echo "Could not copy MeshDeck.py to /usr/bin";
  exit 1; }

# create symbolic link in /usr/sbin
if [ ! -h /usr/sbin/meshdeckd ]; then
 ln -s /usr/bin/MeshDeck.py /usr/sbin/meshdeckd || {
  echo "Failed to create symbolic link in /usr/sbin";
  exit 1; } ;
fi  

# create file in /etc/init.dn
(cp meshdeckd /etc/init.d/. && chmod 744 /etc/init.d/meshdeckd) || {
  echo "Failed to create daemon script in /etc/init.d";
  exit 1; }

# is this a drone?  if so should be automatically start it?
read -p "Set this to automatically run as a drone?" yn
case $yn in
  [Nn]* ) exit;;
  * ) update-rc.d meshdeckd defaults; 
    read -p "start daemon now?" yn
    case $yn in
      [Nn]* ) exit;;
      * ) /etc/init.d/meshdeckd start;;	
    esac
    ;;
esac    
  