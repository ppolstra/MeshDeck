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

This module was initially created by Dr. Philip Polstra for BlackHat Europe 2013.
This updated 2.0 version was created for the book
Hacking and Penetration Testing With Low Power Devices by Dr. Phil

The primary additions to this version are a socket server for the drones
and also the ability to send files

Creative commons share and share alike license.
"""

import serial
from xbee import XBee
from xbee import ZigBee
import time
import signal
import os
import subprocess
from subprocess import Popen, PIPE, call
from struct import *
from multiprocessing import Process
import threading
import random

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
# These are for receiving files from drones
dlpath="./"
receive_file_name={}
receive_file_size={}
receive_file_bytes={}
receive_file_packet_num={}
receive_file_file={}

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
	f = open(w_pipename('%r' % saddr), 'w', 4096)
      else:
        f = open(w_pipename('%r' % saddr), 'a', 4096)
    except OSError:
      pass
    # now add the file to our dictionary
    file_list[saddr] = f
    # lets open a window and tail the file_list
    xterm_str = term + ' ' + term_exec_opt + ' tail -f ' + w_pipename('%r' % saddr)
    subprocess.call(xterm_str.split())
  file_list[saddr].write(data)
  file_list[saddr].flush()
  
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
  elif data['rf_data'].find("ft:") == 0: # drone is attempting to transfer a file
    receive_file_size[saddr] = int(data['rf_data'].split(':')[2])
    receive_file_bytes[saddr] = 0
    receive_file_packet_num[saddr] = 0
    receive_file_name[saddr] = data['rf_data'].split(':')[3]
    if not os.path.exists(dlpath+str(struct.unpack('>h', saddr)[0])): # is there a directory for this drone?
      os.makedirs(dlpath+str(struct.unpack('>h', saddr)[0]))
    receive_file_file[saddr] = open(dlpath+str(struct.unpack('>h', saddr)[0])+'/'+receive_file_name[saddr], 'w')
    print "Receiving file " + receive_file_name[saddr] + " of size " + str(receive_file_size[saddr]) + " from drone " + str(struct.unpack('>h', saddr)[0])
  elif data['rf_data'].find("fd:") == 0: # data packet for a file
    packet_num = int(data['rf_data'].split(':')[2])
    receive_file_packet_num[saddr] += 1
    if (receive_file_packet_num != packet_num):
      print "Warning possible file corruption in file " + receive_file_name[saddr]
    data = str(data['rf_data'].split(':', 3)[3])
    receive_file_bytes[saddr] += len(data)
    receive_file_file[saddr].write(data)
    if (receive_file_bytes[saddr] >= receive_file_size[saddr]):
      print "-----file " + receive_file_name[saddr] + " successfully received-----"
  

"""
This is the main class for the command console.  It
has methods for processing incoming announcements
and also can send commands to drones.
"""
class MeshDeckServer:
  def __init__(self, port, baud):
    self.serial_port = serial.Serial(port, baud) # this is probably /dev/ttyUSB0
    self.xbee = XBee(self.serial_port, callback=dispatch_packets)

  # Send a command to a remote drone  
  def sendCommand(self, cmd, addr='\x00\x00'):
      try:
	respstr = ''
	# send a command to drone
	signal.alarm(5) # give modem 5 seconds to send command
	write_log(addr, "\nCommand send:" + cmd + '\n')
	self.xbee.tx(dest_addr=addr, data="c:"+cmd)
      except Alarm:
	pass
      signal.alarm(0)
      return respstr

# This is a helper function for sending files to drones
# It is primarily intended for sending new scripts 

  def sendFile(self, fname, dnum):
    daddr = pack('BB', dnum/256, dnum % 256) # convert address to '\x00\x01' format used by XBee
    try:
      if not os.path.exists(fname):
	print ("File not found!")
      else:
	flen = os.path.getsize(fname)
	#send the first packet to drone to notify file transfer to start
	self.xbee.tx(dest_addr=daddr, data="ft:1:"+str(flen)+":"+os.path.basename(fname))
	packet_num=1
	# now send the file
	f = open(fname, 'r') # open file as read only
	while True:
	  read_data = f.read(80) # ready 80 bytes at a time to keep < 100 byte packets
	  if not read_data: # must be all done
	    break
	  self.xbee.tx(dest_addr=daddr, data="fd:1:"+str(packet_num)+":"+str(read_data))
	  packet_num += 1
        f.close()
        print "------file transfer successful------"
    except OSError:
      pass

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
	  dnum = int(cmd[1:], 16) # convert hex string to integer
	  daddr = pack('BB', dnum/256, dnum % 256)
	  print("Drone address set to " + str(dnum))
	elif (cmd.find('!') == 0): # first character was ! indicating request to send a file
	  self.sendFile(cmd[1:], dnum) 
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
    self.serial_port = serial.Serial(port, baud) # if using cape /dev/ttyO2
    self.xbee = XBee(self.serial_port)

# This function handles fragmentation of responses from drone scripts/commands
  def sendToController(self, msg):
    resplen = len(msg) # tell the command console how much to expect
    self.xbee.tx(dest_addr='\x00\x00', data="lr:"+str(resplen))
    sentlen = 0
    while sentlen <= resplen:
      endindex = sentlen + 98 # max packet length is 100 bytes
      if (endindex > resplen):
	line = msg[sentlen:]
      else:
	line = msg[sentlen:endindex]
      self.xbee.tx(dest_addr='\x00\x00', data="r:"+line)
      sentlen += 98

# announce an event such as drone start to the command console      
  def sendAnnounce(self, msg):
      self.xbee.tx(dest_addr='\x00\x00', data="a:"+msg)
      
# this is the main loop for the drone clients      
  def clientLoop(self):	
    # Series 2 adapters will have a my address of 0xFFFE until they have an address
    # assigned by the coordinator.  Sending packets without an address could be
    # problematic.  This can be avoided by check for this first
    self.xbee.send('at', frame_id='A', command='MY')
    resp = self.xbee.wait_read_frame()
    while (resp['parameter'] == '\xff\xfe'):
      sleep(1)
      self.xbee.send('at', frame_id='A', command='MY')
      resp = self.xbee.wait_read_frame()
      
    # initial beacon to the controller
    self.sendAnnounce("By your command-drone is awaiting orders")
    # These variables are for transfering files
    rc_size = 0
    rc_bytes = 0
    rc_packet_num = 0
    rc_name = ""
    rc_file = None
    sdl_path = "./"
    
    while True:
      try:
	# get a command from the controller
	cmd = self.xbee.wait_read_frame()
	if (cmd['rf_data'].find('c:') == 0): # sanity check this should be the start of a command
	  self.sendToController("---Process started----\n")
	  proc = subprocess.Popen(cmd['rf_data'][2:], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, bufsize=4096)
	  signal.alarm(3600) # nothing should take an hour to run this will reset a drone if it all goes bad
	  rc = proc.wait() # this call blocks until the process completes
	  signal.alarm(0) # process succeeded so reset the timer
	  if (rc == 0): #returned successfully
            resp = ""
	    for line in iter(proc.stdout.readline, ''):
	      resp += line
	    resp += "---------Process completed successfully------\n"
            self.sendToController(resp)
	  else:
	    self.sendToController("+++++++Process errored out++++++++\n")
	elif (cmd['rf_data'].find("ft:") == 0): # command console is attempting to transfer a file
	  rc_size = int(cmd['rf_data'].split(':')[2])
	  rc_bytes = 0
	  rc_packet_num = 0
	  rc_name = cmd['rf_data'].split(':')[3]
	  rc_file = open(sdl_path+rc_name, 'w')
	elif (cmd['rf_data'].find("fd:") == 0): # data packet for a file
	  packet_num = int(cmd['rf_data'].split(':')[2])
	  rc_packet_num += 1
	  if (rc_packet_num != packet_num):
	    print "Warning possible file corruption in file " + rc_name
	  data = str(cmd['rf_data'].split(':', 3)[3])
	  rc_bytes += len(data)
	  rc_file.write(data)
	  if (rc_bytes >= rc_size):
	    rc_file.close()
      except KeyboardInterrupt:
	break
      except Alarm:
	self.sendToController("+++++++++++Process never completed++++++++++\n")
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
  
