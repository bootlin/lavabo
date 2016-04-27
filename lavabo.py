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

parser_add_user = subparsers.add_parser("add-user", description="Add user to lavabo-server. N.B.: You have to add user's SSH key to the computer hosting lavabo-server.", help="add user to lavabo-server.")
parser_add_user.add_argument("USERNAME", help="username of the user to add to lavabo-server.")

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

parser_upload = subparsers.add_parser("upload", description="Send files to lavabo-server.", help="send files to lavabo-server.")
parser_upload.add_argument("FILES", nargs="+", help="full path of the files to send.")
parser_upload.add_argument("-r", "--rename", nargs="+", help="send each file in FILES to lavabo-server under the given name.")

args = parser.parse_args()

if args.cmd == "upload" and args.rename is not None and len(args.rename) != len(args.FILES):
    print "There is not the same number of arguments for FILES and --rename."
    sys.exit(0)

def get_available_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('', 0))
    addr = sock.getsockname()
    port = addr[1]
    sock.close()
    return port

if args.cmd == "upload":
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

    for local_file, remote_file in zip(args.FILES, args.rename if args.rename is not None else args.FILES):
        sftp_client.put(local_file, os.path.basename(remote_file))
    print "File(s) successfully sent to lavabo-server."

    client.close()
else:
    ssh = subprocess.Popen(("ssh %s@%s interact" % (args.LAVABO_SERVER_USER, args.LAVABO_SERVER)).split(), stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    if args.cmd in ["list", "update"]:
        msg = json.dumps({args.cmd: ""})
    elif args.cmd == "add-user":
        msg = json.dumps({args.cmd: {"username": args.USERNAME}})
    else:
        msg = json.dumps({args.cmd: {"board": args.BOARD}})

    ssh.stdin.write(msg)
    ssh.stdin.flush()
    answer = ssh.stdout.readline()
    ssh.terminate()
    answer = json.loads(answer)

    if args.cmd == "serial" and answer["status"] == "success":
        port = get_available_port()
        ssh = subprocess.Popen(("ssh -N -L %d:localhost:%d %s@%s" % (port, answer["content"]["port"], args.LAVABO_SERVER_USER, args.LAVABO_SERVER)).split())
        serial = None
        for i in range(0,5):
            serial = pexpect.spawn("telnet localhost %d" % port)
            index = serial.expect(["Connected to localhost.", "Connection refused", "Connection closed"])
            if index == 0:
                break
            serial.close()
            if i < 4:
                print "Try %d to connect to serial failed. %d attempts remaining." % (i+1, 5-i-1)
                time.sleep(2)
        if serial.isalive():
            print "You have now access to the serial of %s." % args.BOARD
            serial.interact()
            serial.close()
        else:
            print "error: Could not establish serial connection."
        ssh.terminate()
    else:
        print "%s: %s" % (answer["status"], answer["content"])
