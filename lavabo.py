#! /usr/bin/python2

import socket
import argparse
import json
import os
import subprocess
import paramiko
import getpass
import sys
import pexpect
import time

parser = argparse.ArgumentParser(description="Client to connect to lavabo-server used to remote control boards in LAVA.")
parser.add_argument("LAVABO_SERVER", help="the location of lavabo-server used to remote control boards.")
parser.add_argument("LAVABO_SERVER_USER", help="the user used to connect to lavabo-server.")

subparsers = parser.add_subparsers(dest='cmd', help="subcommands help")

parser_list = subparsers.add_parser("list", description="List all boards available in LAVA.", help="list available boards")

parser_offline = subparsers.add_parser("offline", description="Put board offline.", help="put board offline.")
parser_offline.add_argument("BOARD", help="hostname of the board to put offline.")

parser_online = subparsers.add_parser("online", description="Put board online.", help="put board online.")
parser_online.add_argument("BOARD", help="hostname of the board to put online.")

parser_power_off = subparsers.add_parser("power-off", description="Power board off.", help="power board off.")
parser_power_off.add_argument("BOARD", help="hostname of the board to power off.")

parser_power_on = subparsers.add_parser("power-on", description="Power board on.", help="power board on.")
parser_power_on.add_argument("BOARD", help="hostname of the board to power on.")

parser_serial = subparsers.add_parser("serial", description="Redirect port on lavabo-server to localhost to get serial connection.", help="redirect port on lavabo-server to localhost to get serial connection.")
parser_serial.add_argument("BOARD", help="hostname of the board to get serial connection from.")

parser_status = subparsers.add_parser("status", description="Get board status.", help="get board status.")
parser_status.add_argument("BOARD", help="hostname of the board whose status is requested.")

parser_tftp = subparsers.add_parser("tftp", description="Send or delete files on lavabo-server.", help="send or delete files on lavabo-server.")
parser_tftp.add_argument("FILE", help="path to the file to manage.")

parser_update = subparsers.add_parser("update", description="Update list of available boards.", help="update list of available boards.")

args = parser.parse_args()

def get_available_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('', 0))
    addr = sock.getsockname()
    port = addr[1]
    sock.close()
    return port

if args.cmd == "tftp":
    paramiko.util.log_to_file("paramiko.log")

    client = paramiko.SSHClient()
    #FIXME: loading host keys does not find the right one.
    #host_keys = paramiko.util.load_host_keys(os.path.expanduser('~/.ssh/known_hosts'))
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    username = args.LAVABO_SERVER_USER
    hostname = args.LAVABO_SERVER
    #TODO: Replace this by keyring
    password = getpass.getpass('Password:')
    key = paramiko.RSAKey.from_private_key_file(os.path.expanduser("~/.ssh/id_rsa"), password=password)
    client.connect(hostname, username=username, pkey=key)
    sftp_client = client.open_sftp()

    sftp_client.put(args.FILE, os.path.basename(args.FILE))
    print "File successfully sent to lavabo-server."

    client.close()
else:
    ssh = subprocess.Popen(("ssh %s@%s interact" % (args.LAVABO_SERVER_USER, args.LAVABO_SERVER)).split(), stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    if args.cmd in ["list", "update"]:
        msg = json.dumps({args.cmd: ""})
    else:
        msg = json.dumps({args.cmd: {"board": args.BOARD}})

    ssh.stdin.write(msg)
    ssh.stdin.flush()
    answer = ssh.stdout.readline()
    ssh.terminate()
    answer = json.loads(answer)

    if args.cmd == "serial" and answer["status"] == "success":
        port = get_available_port()
        ssh = subprocess.Popen(("ssh -L %d:localhost:%d %s@%s port-redirection" % (port, answer["content"]["port"], args.LAVABO_SERVER_USER, args.LAVABO_SERVER)).split())
	print "You can now access the serial in localhost on port %d." % port
	raw_input("Press any key to close port redirection.")
        ssh.terminate()
    else:
        print "%s: %s" % (answer["status"], answer["content"])
