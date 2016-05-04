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
from ConfigParser import ConfigParser

parser = argparse.ArgumentParser(description="Client to connect to lavabo-server used to remote control boards in LAVA.")
parser.add_argument("-c", "--conf-file", type=argparse.FileType("r"), default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "lavabo.conf"), help="the location of lavaboconfiguration file. Default: ./lavabo.conf.")

subparsers = parser.add_subparsers(dest='cmd', help="subcommands help")

parser_list = subparsers.add_parser("list", description="List all boards available in LAVA.", help="list available boards")

parser_power_off = subparsers.add_parser("power-off", description="Power board off.", help="power board off.")
parser_power_off.add_argument("BOARD", nargs="?", default=os.environ.get("LAVABO_BOARD", None), help="hostname of the board to power off. If omitted, gotten from LAVABO_BOARD environment variable.")

parser_power_reset = subparsers.add_parser("power-reset", description="Reset board's power.", help="reset board's power.")
parser_power_reset.add_argument("BOARD", nargs="?", default=os.environ.get("LAVABO_BOARD", None), help="hostname of the board to power-reset. If omitted, gotten from LAVABO_BOARD environment variable.")

parser_release = subparsers.add_parser("release", description="Release the board and put it online in LAVA if possible.", help="release the board and put it online in LAVA if possible.")
parser_release.add_argument("BOARD", nargs="?", default=os.environ.get("LAVABO_BOARD", None), help="hostname of the board to put online. If omitted, gotten from LAVABO_BOARD environment variable.")

parser_reserve = subparsers.add_parser("reserve", description="Reserve board and put it offline in LAVA if needed.", help="reserve board and put it offline in LAVA if needed.")
parser_reserve.add_argument("BOARD", nargs="?", default=os.environ.get("LAVABO_BOARD", None), help="hostname of the board to put offline. If omitted, gotten from LAVABO_BOARD environment variable.")

parser_serial = subparsers.add_parser("serial", description="Redirect port on lavabo-server to localhost to get serial connection.", help="redirect port on lavabo-server to localhost to get serial connection.")
parser_serial.add_argument("BOARD", nargs="?", default=os.environ.get("LAVABO_BOARD", None), help="hostname of the board to get serial connection from. If omitted, gotten from LAVABO_BOARD environment variable.")

parser_status = subparsers.add_parser("status", description="Get board status.", help="get board status.")
parser_status.add_argument("BOARD", nargs="?", default=os.environ.get("LAVABO_BOARD", None), help="hostname of the board whose status is requested. If omitted, gotten from LAVABO_BOARD environment variable.")

parser_upload = subparsers.add_parser("upload", description="Send files to lavabo-server.", help="send files to lavabo-server.")
parser_upload.add_argument("FILES", nargs="+", help="full path of the files to send. You can rename the files after being uploaded by separating local filenames and remote filenames with a colon (:). e.g.: upload file1:file2 file2:file3 will upload file1 and file2 and respectively rename them file2 and file3 on lavabo-server.")

args = parser.parse_args()

config_parser = ConfigParser()
config_parser.readfp(args.conf_file)
hostname = config_parser.get("lavabo-server", "hostname")
user = config_parser.get("lavabo-server", "user")
port = config_parser.getint("lavabo-server", "port")

if args.cmd not in ["upload", "list"] and args.BOARD is None:
    print "No board specified. Please add board in LAVABO_BOARD environment variable or as an argument to the command."
    sys.exit(1)

def get_available_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('', 0))
    addr = sock.getsockname()
    local_port = addr[1]
    sock.close()
    return local_port

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

    transport = paramiko.Transport((hostname, port))
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
    if hostname not in keys or key.get_name() not in keys[hostname]:
        print "WARNING: Unknown host key!"
    elif keys[hostname][key.get_name()] != key:
        print "ERROR: Host key has changed!!! Avoiding connection."
        sys.exit(1)

    agent_auth(transport, user)
    if not transport.is_authenticated():
        print "ERROR: Authentication failed."
        transport.close()
        sys.exit(1)
    sftp_client = transport.open_sftp_client()

    for upload in args.FILES:
        paths = upload.split(":")
        local_path = paths[0]
        remote_file = os.path.basename(paths[1]) if len(paths) == 2 else os.path.basename(local_path)
        sftp_client.put(local_path, remote_file)
    print "File(s) successfully sent to lavabo-server."

    sftp_client.close()
    transport.close()
else:
    ssh = subprocess.Popen(("ssh %s@%s -p %d interact" % (user, hostname, port)).split(), stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    if args.cmd in ["list", "update"]:
        msg = json.dumps({args.cmd: ""})
    else:
        msg = json.dumps({args.cmd: {"board": args.BOARD}})

    ssh.stdin.write(msg)
    ssh.stdin.flush()
    answer = ssh.stdout.readline()
    ssh.terminate()
    try:
        answer = json.loads(answer)
    except ValueError as e:
        print e
        sys.exit(1)

    if args.cmd == "serial" and answer["status"] == "success":
        local_port = get_available_port()
        ssh = subprocess.Popen(("ssh -N -L %d:localhost:%d %s@%s -p %d" % (local_port, answer["content"]["port"], user, hostname, port)).split())
        serial = None
        for i in range(0,5):
            serial = pexpect.spawn("telnet localhost %d" % local_port)
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
            sys.exit(1)
        ssh.terminate()
    else:
        if answer["status"] == "error":
            print "%s: %s" % (answer["status"], answer["content"])
            sys.exit(1)
        content = answer["content"]
        if args.cmd == "list":
            print "\n".join(content)
        elif args.cmd == "status":
            print "%s is %s%s%s%s" % (content["hostname"], content["status"], (" job %d" % content["job"]) if content["job"] else "", (" by %s" % content["offline_by"]) if content["offline_by"] else "", (" since %s" % content["offline_since"]) if content["offline_since"] else "")
