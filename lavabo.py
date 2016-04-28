#! /usr/bin/python2

import socket
import argparse
import json
import os
import subprocess
import paramiko
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

parser_power_off = subparsers.add_parser("power-off", description="Power board off.", help="power board off.")
parser_power_off.add_argument("BOARD", help="hostname of the board to power off.")

parser_power_on = subparsers.add_parser("power-on", description="Power board on.", help="power board on.")
parser_power_on.add_argument("BOARD", help="hostname of the board to power on.")

parser_release = subparsers.add_parser("release", description="Release the board and put it online in LAVA if possible.", help="release the board and put it online in LAVA if possible.")
parser_release.add_argument("BOARD", help="hostname of the board to put online.")

parser_reserve = subparsers.add_parser("reserve", description="Reserve board and put it offline in LAVA if needed.", help="reserve board and put it offline in LAVA if needed.")
parser_reserve.add_argument("BOARD", help="hostname of the board to put offline.")

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

def agent_auth(transport, username):
    """
    Attempt to authenticate to the given transport using any of the private
    keys available from an SSH agent.
    """

    agent = paramiko.Agent()
    agent_keys = agent.get_keys()
    if len(agent_keys) == 0:
        return

    for key in agent_keys:
        try:
            transport.auth_publickey(username, key)
            print "Successfull authentication."
            return
        except paramiko.SSHException:
            pass

if args.cmd == "upload":
    paramiko.util.log_to_file("paramiko.log")

    transport = paramiko.Transport((args.LAVABO_SERVER, 22))
    try:
        transport.start_client()
    except paramiko.SSHException:
        print "SSH negotiation failed."
        sys.exit(1)
    try:
        keys = paramiko.util.load_host_keys(os.path.expanduser("~/.ssh/known_hosts"))
    except IOError:
        keys = {}

    key = transport.get_remote_server_key()
    if args.LAVABO_SERVER not in keys or key.get_name() not in keys[args.LAVABO_SERVER]:
        print "WARNING: Unknown host key!"
    elif keys[args.LAVABO_SERVER][key.get_name()] != key:
        print "ERROR: Host key has changed!!! Avoiding connection."
        sys.exit(1)

    agent_auth(transport, args.LAVABO_SERVER_USER)
    if not transport.is_authenticated():
        print "ERROR: Authentication failed."
        transport.close()
        sys.exit(1)
    sftp_client = transport.open_sftp_client()

    for local_file, remote_file in zip(args.FILES, args.rename if args.rename is not None else args.FILES):
        sftp_client.put(local_file, os.path.basename(remote_file))
    print "File(s) successfully sent to lavabo-server."

    sftp_client.close()
    transport.close()
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
