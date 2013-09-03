#!/usr/bin/python

"""
MeshDeck Python module
This module implements the MeshDeck which is an addon to The Deck which allows
multiple devices running The Deck to communicate via 802.15.4 Xbee and/or
ZigBee mesh networking.  This allows coordinated attacks to be performed.
A centralized command console is used to coordinate with the drones.

Drones will accept commands from the command console and will report results back.
Drones can also periodically send announcements to the command console about
important events or to announce their availability to receive commands.

The command console will continually monitor the Xbee radio for incoming 
announcements.  A main announcement window will display all announcements.
Upon hearing from a new drone, a window will be opened to allow commands to be sent 
to that drone.

This module was created by Dr. Philip Polstra for BlackHat Europe 2013.
Creative commons share and share alike license.
"""

import serial
from xbee import XBee
import time
import signal
import os
import subprocess
from subprocess import Popen, PIPE, call
from struct import *

#what terminal program would we like to use?
term = 'konsole'
term_title_opt = '-T'
term_exec_opt = '-e'

def usage():
  print "MeshDeck communications module"
  print "Usage:"
  print "  Run server"
  print "    meshdeck.py -s [device] [baud] "
  print "  Run drone"
  print "    meshdeck.py -d [device] [baud] "
  print "  Send announcement and exit"
  print "    meshdeck.py -a [device] [baud] 'quoted announcement'"

# This is just a helper class that is used by the server to prevent
# communications with a drone from hanging
class Alarm(Exception):
  pass

def alarm_handler(signum, frame):
  raise Alarm

signal.signal(signal.SIGALRM, alarm_handler)

#helper functions for the dispatcher
def r_pipename(addr):
  return "/tmp/rp" + addr[3:5] + addr[7:9]

def w_pipename(addr):
  return "/tmp/wp" + addr[3:5] + addr[7:9]
  
#This list is used to keep track of drones I have seen
drone_list=[]
file_list={}

"""
This function writes commands, announcements
and responses to the appropriate file log.
If a drone hasn't been heard from before
the appropriate file is openned and the file
object is added to the list of files.
"""
def write_log(saddr, data):
  if saddr not in drone_list:
    drone_list.append(saddr)
    # open the appropriate file
    try:
      if not os.path.exists(w_pipename('%r' % saddr)):
	f = open(w_pipename('%r' % saddr), 'w', 100)
      else:
        f = open(w_pipename('%r' % saddr), 'a', 100)
    except OSError:
      pass
    # now add the file to our dictionary
    file_list[saddr] = f
    # lets open a window and tail the file_list
    xterm_str = term + ' ' + term_exec_opt + ' tail -f ' + w_pipename('%r' % saddr)
    subprocess.call(xterm_str.split())
  file_list[saddr].write(data)
  
#This is the main handler for received XBee packets
# it is automatically called when a new packet is received
def dispatch_packets(data):
  # is this a drone that I used to know?
  saddr = data['source_addr']
  # response length
  if data['rf_data'].find("lr:") == 0:
    #write_log(saddr, "Expecting " + data['rf_data'][3:] + " from address " + '%r' % data['source_addr'] + '\n')
    pass
  elif data['rf_data'].find("r:") == 0:
    write_log(saddr, data['rf_data'][2:])
  elif data['rf_data'].find("a:") == 0:
    write_log(saddr, '\n' + "Announcement:" + data['rf_data'][2:] + '\n')
  

"""
This is the main class for the command console.  It
has methods for processing incoming announcements
and also can send commands to drones.
"""
class MeshDeckServer:
  def __init__(self, port, baud):
    self.serial_port = serial.Serial(port, baud)
    self.xbee = XBee(self.serial_port, callback=dispatch_packets)

  # Send a command to a remote drone  
  def sendCommand(self, cmd, addr='\x00\x00'):
      try:
	respstr = ''
	# send a command to drone
	signal.alarm(5)
	write_log(addr, "\nCommand send:" + cmd + '\n')
	self.xbee.tx(dest_addr=addr, data="c:"+cmd)
      except Alarm:
	pass
      signal.alarm(0)
      return respstr
  
  # This is the main processing loop.  It
  # receives and sends commands.  The responses
  # and announcements are automatically processed by
  # the callback function above.
  def serverLoop(self):
    dnum = 1
    daddr=pack('BB', dnum/256, dnum % 256) # default to drone 1
    while True:
      try:
	cmd = raw_input("Enter command for " + str(dnum) + ">")
	if (cmd.find(':') == 0): # first character was : indicating change of drone
	  dnum = int(cmd[1:], 16)
	  daddr = pack('BB', dnum/256, dnum % 256)
	  print("Drone address set to " + str(dnum))
	else:
	  self.sendCommand(cmd, addr=daddr)
      except KeyboardInterrupt:
	      break
    self.serial_port.close()

"""
Class for Drones or Clients
"""
class MeshDeckClient:
  def __init__(self, port, baud):
    self.serial_port = serial.Serial(port, baud)
    self.xbee = XBee(self.serial_port)

  def sendToController(self, msg):
    resplen = len(msg)
    self.xbee.tx(dest_addr='\x00\x00', data="lr:"+str(resplen))
    sentlen = 0
    while sentlen <= resplen:
      endindex = sentlen + 98
      if (endindex > resplen):
	line = msg[sentlen:]
      else:
	line = msg[sentlen:endindex]
      self.xbee.tx(dest_addr='\x00\x00', data="r:"+line)
      sentlen += 98

  def sendAnnounce(self, msg):
      self.xbee.tx(dest_addr='\x00\x00', data="a:"+msg)
      
  def clientLoop(self):	
    # initial beacon to the controller
    self.sendAnnounce("By your command-drone is awaiting orders")
    
    while True:
      try:
	# get a command from the controller
	cmd = self.xbee.wait_read_frame()
	if (cmd['rf_data'].find('c:') == 0): # sanity check this should be the start of a command
	  proc = subprocess.Popen(cmd['rf_data'][2:], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
	  signal.alarm(60)
	  rc = proc.wait()
	  signal.alarm(0)
	  if (rc == 0): #returned successfully
	    for line in iter(proc.stdout.readline, ''):
	      self.sendToController(line)
	  else:
	    self.sendToController("Error: process returned " + str(rc) + "\n")
      except KeyboardInterrupt:
	break
      except Alarm:
	self.sendToController("Error: process timed out")
	signal.alarm(0)
    self.serial_port.close()
 
#run the server by default
if __name__ == "__main__":
  import sys
  if (len(sys.argv) < 2) or (sys.argv[1] == "-s"): # server mode -s device baud
    if len(sys.argv) > 3: # device and baud passed
      mdserver = MeshDeckServer(sys.argv[2], eval(sys.argv[3]))
    else:
      mdserver = MeshDeckServer("/dev/ttyUSB0", 57600)
    mdserver.serverLoop()
  elif (sys.argv[1] == '-d'): # drone mode
    if len(sys.argv) > 3: # device and baud passed
      mdclient = MeshDeckClient(sys.argv[2], eval(sys.argv[3]))
    else:
      mdclient = MeshDeckClient("/dev/ttyO2", 57600)
    try:
      pid = os.fork()
      if pid > 0:
	# we are in the parent
	sys.exit(0)
    except OSError, e:
      print >>sys.stderr, "fork failed: %d (%s)" % (e.errno, e.strerror)
      sys.exit(1)
    mdclient.clientLoop()
  elif (sys.argv[1] == '-a'): # just make an announcement and exit
    if len(sys.argv) > 4: #device and baud rate passed
      mdclient = MeshDeckClient(sys.argv[2], eval(sys.argv[3]))
      mdclient.sendAnnounce(sys.argv[4])
    else:
      mdclient = MeshDeckClient("/dev/ttyO2", 57600)
      mdclient.sendAnnounce(sys.argv[2])  
  else:
    usage()
  
