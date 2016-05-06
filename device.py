#! /usr/bin/python2

import xmlrpclib
import subprocess
import utils
from os import devnull

class Device(object):

    def __init__(self, name, reset_command, off_command, serial_command):
        self.name = name
        self.reset_command = reset_command
        self.off_command = off_command
        self.serial_command = serial_command

    def put_offline(self, user, proxy):
        try:
            return proxy.scheduler.put_into_maintenance_mode(self.name, "Put offline by %s" % user)
        except xmlrpclib.Fault as e:
            return utils.create_json("error", "XMLRPC err%d: %s" % (e.faultCode, e.faultString))

    def put_online(self, user, proxy):
        try:
            return proxy.scheduler.put_into_online_mode(self.name, "Put online by %s" % user)
        except xmlrpclib.Fault as e:
            return utils.create_json("error", "XMLRPC err%d: %s" % (e.faultCode, e.faultString))

    def get_status(self, proxy):
        try:
            return proxy.scheduler.get_device_status(self.name)
        except xmlrpclib.Fault as e:
            return utils.create_json("error", "XMLRPC err%d: %s" % (e.faultCode, e.faultString))

    def power_reset(self):
        return subprocess.call(self.reset_command.split(), stdout=open(devnull, 'wb'))

    def power_off(self):
        return subprocess.call(self.off_command.split(), stdout=open(devnull, 'wb'))

    def get_serial_port(self):
        return self.serial_command.split()[2]
