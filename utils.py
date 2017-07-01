#! /usr/bin/python2

#  Copyright 2016 Quentin Schulz <quentin.schulz@free-electrons.com>
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.

import StringIO
import os
from ConfigParser import ConfigParser
import device
import sqlite3
import json
import fcntl
import time
import ssl
import urlparse
import xmlrpclib
import re
import subprocess
from os import devnull

def get_simple_device_list(proxy):
    return proxy.scheduler.all_devices()

def get_serial_port(proxy, device_name):
    try:
        device_dict = str(proxy.scheduler.export_device_dictionary(device_name))
    except xmlrpclib.Fault as e:
        return None

    serial_command_re = re.compile("connection_command = '.* .* (\d*)'")
    try:
        return int(serial_command_re.search(device_dict).group(1))
    except:
        return None

def power_reset(proxy, device_name):
    try:
        device_dict = str(proxy.scheduler.export_device_dictionary(device_name))
    except xmlrpclib.Fault as e:
        return -1

    reset_command_re = re.compile("hard_reset_command = '(.*)'")
    try:
        reset_command = reset_command_re.search(device_dict).group(1)
    except:
        return -2

    return subprocess.call(reset_command.split(), stdout=open(devnull, 'wb'))

def power_off(proxy, device_name):
    try:
        device_dict = str(proxy.scheduler.export_device_dictionary(device_name))
    except xmlrpclib.Fault as e:
        return -1

    off_command_re = re.compile("power_off_command = '(.*)'")
    try:
        off_command = off_command_re.search(device_dict).group(1)
    except:
        return -2

    return subprocess.call(off_command.split(), stdout=open(devnull, 'wb'))

def put_offline(proxy, device_name, user):
    try:
        proxy.scheduler.put_into_maintenance_mode(device_name, "Put offline by %s" % user)
        return None
    except xmlrpclib.Fault as e:
        return utils.create_json("error", "XMLRPC err%d: %s" % (e.faultCode, e.faultString))

def put_online(proxy, device_name, user):
    try:
        proxy.scheduler.put_into_online_mode(device_name, "Put online by %s" % user)
        return None
    except xmlrpclib.Fault as e:
        return utils.create_json("error", "XMLRPC err%d: %s" % (e.faultCode, e.faultString))

def create_json(status, content):
    return {"status": status, "content": content}

def create_answer(status, content):
    return json.dumps(create_json(status, content))

def acquire_lock(lock, tries=5):
    for i in range(0,tries):
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except IOError:
            if i == tries-1:
                return False
            time.sleep(0.1)
    return True

def release_lock(lock):
    fcntl.flock(lock, fcntl.LOCK_UN)

# Taken from: https://github.com/kernelci/lava-ci/blob/master/lib/utils.py
def validate_input(username, token, server):
    url = urlparse.urlparse(server)
    if url.path.find('RPC2') == -1:
        print "LAVA Server URL must end with /RPC2"
        sys.exit(1)
    return url.scheme + '://' + username + ':' + token + '@' + url.netloc + url.path

def connect(url):
    try:
        if 'https' in url:
            context = hasattr(ssl, '_create_unverified_context') and ssl._create_unverified_context() or None
            connection = xmlrpclib.ServerProxy(url, transport=xmlrpclib.SafeTransport(use_datetime=True, context=context))
        else:
            connection = xmlrpclib.ServerProxy(url)
        return connection
    except (xmlrpclib.ProtocolError, xmlrpclib.Fault, IOError) as e:
        print "Unable to connect to %s" % url
        sys.exit(1)

def init_db():
    db_conn = sqlite3.connect("remote-control.db")
    db_cursor = db_conn.cursor()
    db_cursor.execute("CREATE TABLE IF NOT EXISTS users (username PRIMARY KEY)")
    db_cursor.execute("CREATE TABLE IF NOT EXISTS devices (hostname PRIMARY KEY)")
    db_cursor.execute("CREATE TABLE IF NOT EXISTS reservations (device_name, last_use INTEGER, made_by, reserved INTEGER, FOREIGN KEY(device_name) REFERENCES devices(hostname), FOREIGN KEY(made_by) REFERENCES users(username))")
    db_conn.commit()
    db_cursor.close()
    return db_conn
