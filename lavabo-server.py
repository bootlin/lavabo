#! /usr/bin/python2

import xmlrpclib
import os
import time
from ConfigParser import ConfigParser
import argparse
import json
import subprocess
import sqlite3
import select
import paramiko
import sys
import fcntl
import urlparse
import ssl
import StringIO

parser = argparse.ArgumentParser(description="Server to allow remote controlling of boards in LAVA.")
parser.add_argument("LAVABO_USER", help="user to authenticate against in lavabo")

parser.add_argument("-c", "--conf-file", type=argparse.FileType("r"), default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "lavabo-server.conf"), help="the location of lavabo-server configuration file. Default: ./lavabo-server.conf.")

parser.add_argument('--tftp-dir', default="/var/lib/lava/dispatcher/tmp/", help="the TFTP root directory used to serve files to boards.")

subparsers = parser.add_subparsers(dest='cmd', help="subcommands help")
parser_sftp = subparsers.add_parser("internal-sftp", description="Launch sftp server.", help="launch sftp-server.")

parser_interact = subparsers.add_parser("interact", description="Listen to stdin and answer to stdout.", help="listen to stdin and answer to stdout.")

parser_interact.add_argument('--devices-conf-dir', default="/etc/lava-dispatcher/devices/", help="the directory used to store LAVA device configuration files.")

class Device(object):

    def __init__(self, name, reset_command, off_command, serial_command):
        self.name = name
        self.reset_command = reset_command
        self.off_command = off_command
        self.serial_command = serial_command

    def put_offline(self, user):
        return proxy.scheduler.put_into_maintenance_mode(self.name, "Put offline by %s" % user)

    def put_online(self, user):
        return proxy.scheduler.put_into_online_mode(self.name, "Put online by %s" % user)

    def get_status(self):
        return proxy.scheduler.get_device_status(self.name)

    def power_reset(self):
        return subprocess.call(self.reset_command.split(), stdout=open(os.devnull, 'wb'))

    def power_off(self):
        return subprocess.call(self.off_command.split(), stdout=open(os.devnull, 'wb'))

    def get_serial_port(self):
        return self.serial_command.split()[2]

def get_device_list(db_conn):
    devices.clear()
    config_parser = ConfigParser()

    for conf_file in os.listdir(args.devices_conf_dir):
        conf = StringIO.StringIO()
        conf.write('[__main__]\n')
        conf.write(open(os.path.join(args.devices_conf_dir, conf_file)).read())
        conf.seek(0)
        config_parser.readfp(conf)
        device_name = config_parser.get("__main__", "hostname")
        reset_command = config_parser.get("__main__", "hard_reset_command")
        off_command = config_parser.get("__main__", "power_off_cmd")
        serial_command = config_parser.get("__main__", "connection_command")
        devices[device_name] = Device(device_name, reset_command, off_command, serial_command)
        db_cursor = db_conn.cursor()
        try:
            db_cursor.execute("INSERT INTO devices VALUES (?)", (device_name,))
            db_cursor.execute("INSERT INTO reservations VALUES (?, ?, ?, ?)", (device_name, 0, None, 0))
            db_conn.commit()
        except sqlite3.IntegrityError:
            pass
        finally:
            db_cursor.close()
    return devices

def exists(device_name):
    return device_name in devices

def list_devices():
    return sorted(devices.keys())

def create_answer(status, content):
    answer = {}
    answer["status"] = status
    answer["content"] = content
    return json.dumps(answer)

def get_status(db_cursor, device_name):
    if not exists(device_name):
        return create_answer("error", "Device does not exist.")
    device = proxy.scheduler.get_device_status(device_name)
    if device["status"] == "offline":
        if device["offline_by"] != lava_user:
            device["offline_by"] = "Unknown, outside lavabo"
        else:
            db_cursor.execute("SELECT last_use, made_by, reserved FROM reservations WHERE device_name = ? ORDER BY last_use DESC", (device_name,))
            #FIXME: Fetchone possibly returns None
            reservation = db_cursor.fetchone()
            last_use, made_by, reserved = reservation
            device["offline_since"] = time.ctime(last_use)
            if reserved == 0:
                device["status"] = "reservable"
                device["offline_by"] = None
            else:
                device["offline_by"] = made_by
    return create_answer("success", device)

def get_serial(db_cursor, user, device_name):
    if not exists(device_name):
        return create_answer("error", "Device does not exist.")
    for i in range(0,5):
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except IOError:
            if i == 4:
                return create_message("error", "Could not acquire lock.")
            time.sleep(0.1)
    device = proxy.scheduler.get_device_status(device_name)
    try:
        if device["status"] != "offline" or device["offline_by"] != lava_user:
            return create_answer("error", "Device is not offline in LAVA or has been reserved in LAVA without this tool.")
        db_cursor.execute("SELECT last_use, made_by, reserved FROM reservations WHERE device_name = ? ORDER BY last_use DESC", (device_name,))
        #FIXME: Fetchone possibly returns None
        reservation = db_cursor.fetchone()
        last_use, made_by, reserved = reservation
        if reserved == 0:
            return create_answer("error", "You have to reserve the device.")
        if made_by != user:
            return create_answer("error", "Device reserved by %s and lastly used %s." % (made_by, time.ctime(last_use)))
        return create_answer("success", {"port": int(devices[device_name].get_serial_port())})
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)

def power_reset(db_cursor, user, device_name):
    if not exists(device_name):
        return create_answer("error", "Device does not exist.")
    for i in range(0,5):
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except IOError:
            if i == 4:
                return create_message("error", "Could not acquire lock.")
            time.sleep(0.1)
    device = proxy.scheduler.get_device_status(device_name)
    try:
        if device["status"] != "offline" or device["offline_by"] != lava_user:
            return create_answer("error", "Device is not offline in LAVA or has been reserved in LAVA without this tool.")
        db_cursor.execute("SELECT last_use, made_by, reserved FROM reservations WHERE device_name = ? ORDER BY last_use DESC", (device_name,))
        #FIXME: Fetchone possibly returns None
        reservation = db_cursor.fetchone()
        last_use, made_by, reserved = reservation
        if reserved == 0:
            return create_answer("error", "You have to reserve the device.")
        if made_by != user:
            return create_answer("error", "Device reserved by %s and lastly used %s." % (made_by, time.ctime(last_use)))
        if devices[device_name].power_reset() == 0:
            return create_answer("success", "Device successfully powered on.")
        return create_answer("error", "Failed to power on device.")
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)

def power_off(db_cursor, user, device_name):
    if not exists(device_name):
        return create_answer("error", "Device does not exist.")
    for i in range(0,5):
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except IOError:
            if i == 4:
                return create_message("error", "Could not acquire lock.")
            time.sleep(0.1)
    device = proxy.scheduler.get_device_status(device_name)
    try:
        if device["status"] != "offline" or device["offline_by"] != lava_user:
            return create_answer("error", "Device is not offline in LAVA or has been reserved in LAVA without this tool.")
        db_cursor.execute("SELECT last_use, made_by, reserved FROM reservations WHERE device_name = ? ORDER BY last_use DESC", (device_name,))
        #FIXME: Fetchone possibly returns None
        reservation = db_cursor.fetchone()
        last_use, made_by, reserved = reservation
        if reserved == 0:
            return create_answer("error", "You have to reserve the device.")
        if made_by != user:
            return create_answer("error", "Device reserved by %s and lastly used %s." % (made_by, time.ctime(last_use)))
        if devices[device_name].power_off() == 0:
            return create_answer("success", "Device successfully powered off.")
        return create_answer("error", "Failed to power off device.")
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)

def put_offline(db_cursor, user, device_name, thief=False, cancel_job=False, force=False):
    if not exists(device_name):
        return create_answer("error", "Device does not exist.")
    for i in range(0,5):
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except IOError:
            if i == 4:
                return create_message("error", "Could not acquire lock.")
            time.sleep(0.1)
    device = proxy.scheduler.get_device_status(device_name)
    try:
        if device["status"] == "idle":
            if devices[device_name].put_offline(user):
                return create_answer("error", "Failed to put device offline.")
            db_cursor.execute("INSERT INTO reservations VALUES (?, ?, ?, ?)", (device_name, time.time(), user, 1))
            db_cursor.connection.commit()
            return create_answer("success", "Device put offline.")
        if device["status"] == "offline":
            if device["offline_by"] != lava_user:
                return create_answer("error", "Device has been reserved in LAVA without this tool.")
            db_cursor.execute("SELECT last_use, made_by, reserved FROM reservations WHERE device_name = ? ORDER BY last_use DESC", (device_name,))
            #FIXME: Fetchone possibly returns None
            reservation = db_cursor.fetchone()
            last_use, made_by, reserved = reservation
            if reserved == 1:
                if made_by != user:
                    return create_answer("error", "Device reserved by %s and lastly used %s." % (made_by, time.ctime(last_use)))
                return create_answer("success", "You have already put this device offline.")
            db_cursor.execute("INSERT INTO reservations VALUES (?, ?, ?, ?)", (device_name, time.time(), user, 1))
            db_cursor.connection.commit()
            return create_answer("success", "Device put offline.")
        #FIXME: What about reserved, offlining, running?
        return create_answer("error", "Device is probably running a job.")
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)

def put_online(db_cursor, user, device_name, force=False):
    if not exists(device_name):
        return create_answer("error", "Device does not exist.")
    for i in range(0,5):
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except IOError:
            if i == 4:
                return create_message("error", "Could not acquire lock.")
            time.sleep(0.1)
    device = proxy.scheduler.get_device_status(device_name)
    try:
        if device["status"] == "idle":
            return create_answer("success", "Device is already online.")
        if device["status"] == "offline":
            if device["offline_by"] != lava_user:
                return create_answer("error", "Device has been reserved in LAVA without this tool.")
            db_cursor.execute("SELECT last_use, made_by, reserved FROM reservations WHERE device_name = ? ORDER BY last_use DESC", (device_name,))
            #FIXME: Fetchone possibly returns None
            reservation = db_cursor.fetchone()
            last_use, made_by, reserved = reservation
            if made_by == user:
                if devices[device_name].put_online(user):
                    return create_answer("error", "Failed to put device online.")
                db_cursor.execute("INSERT INTO reservations VALUES (?, ?, ?, ?)", (device_name, time.time(), user, 0))
                db_cursor.connection.commit()
                return create_answer("success", "Device put online.")
            return create_answer("error", "Device reserved by %s and lastly used %s." % (made_by, time.ctime(last_use)))
        #FIXME: What about reserved, offlining, running?
        return create_answer("error", "Device is probably running a job.")
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)

def add_user(db_cursor, username):
    try:
        db_cursor.execute("INSERT INTO users VALUES (?)", (username,))
    except sqlite3.IntegrityError:
        return create_answer("error", "Failed to create user, %s is already used." % username)
    try:
        os.mkdir(os.path.join(args.tftp_dir, username))
    except OSError:
        # Directory exists prior to user creation or UNIX user who
        # launched lavabo-server has unsufficient permission to create
        # a subdirectory in TFTP directory.
        # Test if the UNIX user who launched lavabo-server has
        # sufficient permission to write, read or execute in this directory.
        if not os.access(os.path.join(args.tftp_dir, username), os.R_OK | os.W_OK | os.X_OK):
            return create_answer("error", "Failed to create or access subdirectory for user in TFTP directory. Check UNIX permissions.")
    db_cursor.connection.commit()
    return create_answer("success", "User %s successfully created. Adding user's SSH key to lavabo-server is needed to complete user creation." % username)

def handle(data, stdout):
    try:
        data = json.loads(data)
    except ValueError as e:
        os.write(stdout, create_answer("error", "Unable to parse request. Skipping.")+"\n")
        return
    user = args.LAVABO_USER
    db_cursor = db_conn.cursor()
    try:
        db_cursor.execute('SELECT * FROM users WHERE username = ?', (user,))
        db_user = db_cursor.fetchone()
        if not db_user:
            ans = add_user(db_cursor, user)
            if ans["status"] == "error":
                os.write(stdout, json.dumps(ans)+"\n")
                return
        ans = create_answer("error", "Missing board name.")
        if "list" in data:
            ans = create_answer("success", list_devices())
        elif "upload" in data:
            ans = create_answer("success", str(os.path.join(args.tftp_dir, user)))
        #This is status from LAVA, offline_by will always be "daemon"
        #TODO: Add a status_remote to display the user who is working on the board
        elif "status" in data:
            if "board" in data["status"]:
                ans = get_status(db_cursor, data["status"]["board"])
        elif "serial" in data:
            if "board" in data["serial"]:
                ans = get_serial(db_cursor, user, data["serial"]["board"])
        elif "release" in data:
            if "board" in data["release"]:
                ans = put_online(db_cursor, user, data["release"]["board"], data["release"].get("force", False))
        elif "reserve" in data:
            if "board" in data["reserve"]:
                ans = put_offline(db_cursor, user, data["reserve"]["board"], data["reserve"].get("thief", False), data["reserve"].get("cancel_job", False))
        elif "power-reset" in data:
            if "board" in data["power-reset"]:
                ans = power_reset(db_cursor, user, data["power-reset"]["board"])
        elif "power-off" in data:
            if "board" in data["power-off"]:
                ans = power_off(db_cursor, user, data["power-off"]["board"])
        else:
            ans = create_answer("error", "Unknown command.")
        os.write(stdout, ans+"\n")
    finally:
        db_cursor.close()

# Taken from https://github.com/jborg/attic/blob/master/attic/remote.py
BUFSIZE = 10 * 1024 * 1024

def serve():
    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    # Make stdin non-blocking
    fl = fcntl.fcntl(stdin_fd, fcntl.F_GETFL)
    fcntl.fcntl(stdin_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
    # Make stdout blocking
    fl = fcntl.fcntl(stdout_fd, fcntl.F_GETFL)
    fcntl.fcntl(stdout_fd, fcntl.F_SETFL, fl & ~os.O_NONBLOCK)
    while True:
       r, w, es = select.select([stdin_fd], [], [], 10)
       if r:
           data = os.read(stdin_fd, BUFSIZE)
           if not data:
               return
           handle(data, stdout_fd)
    db_conn.close()

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
    global db_conn
    db_conn = sqlite3.connect("remote-control.db")
    db_cursor = db_conn.cursor()
    db_cursor.execute("CREATE TABLE IF NOT EXISTS users (username PRIMARY KEY)")
    db_cursor.execute("CREATE TABLE IF NOT EXISTS devices (hostname PRIMARY KEY)")
    db_conn.execute("CREATE TABLE IF NOT EXISTS reservations (device_name, last_use INTEGER, made_by, reserved INTEGER, FOREIGN KEY(device_name) REFERENCES devices(hostname), FOREIGN KEY(made_by) REFERENCES users(username))")
    db_conn.commit()
    db_cursor.close()

args = parser.parse_args()
config_parser = ConfigParser()
config_parser.readfp(args.conf_file)
lava_user = config_parser.get("lava-api", "user")
lava_token = config_parser.get("lava-api", "token")
lava_url = config_parser.get("lava-api", "url")

devices = {}
proxy = None
db_conn = None
lock = open("lavabo-server.lock", "w+")

init_db()
url = validate_input(lava_user, lava_token, lava_url)
proxy = connect(url)

if args.cmd == "internal-sftp":
    subprocess.call(("/usr/lib/openssh/sftp-server -d %s" % os.path.join(args.tftp_dir, args.LAVABO_USER)).split())
else:
    get_device_list(db_conn)
    serve()
