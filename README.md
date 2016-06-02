# lavabo

lavabo is a tool to allow developers to work on boards that are inside a [LAVA](http://www.linaro.org/initiatives/lava/) infrastructure.

## Requirements

- ser2net on LAVA instance to serve serial;

## Limitations

- only devices from the LAVA master node are remotely controllable by lavabo;

## Configuration

### lavabo-server

Create a new user and its authentication token in your LAVA instance for the tool to interact with it.

Add your SSH key to the authorized\_keys of one user on your LAVA instance:

```
$ ssh-copy-id user@lava_server
```

Open `/home/user/.ssh/authorized_keys` and add `command="python /path/to/lavabo-server lavabo_user $SSH_ORIGINAL_COMMAND"` at the beginning of every key in this file.

`lavabo_user` is the name given in lavabo to the user authenticating with this SSH key. It is the name used to make sure not more than one developer is accessing a board at the same time.

Give sufficient permission to `user` to create directories in the TFTP directory used by LAVA (as advised when installing LAVA, it should be `/var/lib/lava/dispatcher/tmp` or look at `/etc/default/tftpd-hpa`):

```
 # chgrp user /var/lib/lava/dispatcher/tmp
 # chmod g+rwx /var/lib/lava/dispacther/tmp
```

Complete the lavabo-server.conf with `user` and `token` being the credentials for authenticating lavabo-server on LAVA instance and `url` being the URL of the LAVA server API (it should end with `/RPC2`).

### lavabo

Install lavabo dependency:

```
 # apt-get install python-paramiko python-argcomplete
```

Copy ```lavabo.conf`` as ```$HOME/.lavabo.conf``` and adapt it with the appropriate settings.

## F.A.Q

### Why?

We have a LAVA lab with boards we often own in only one copy. We have these boards included in [KernelCI project](https://kernelci.org/) which sends tests for different kernels to our LAVA lab in order to know if everything is working on the boards in our lab.

However, we sometime need to have direct access to the board when work on the kernel is in progress. We do not want to put the board physically outside of the lab each time we want to work on it. This means we want to be able to remotely power it on or off, get its serial connection and send files to it.

As we want to work on the board without being interrupted by LAVA, we also have to virtually put the board outside of our lab.

### What can lavabo do on a board?

`$ lavabo -h` should be enough and is up-to-date.

### How are files served to the board?

LAVA uses TFTP to serve files to the board, so all we need is to send files from our laptop to the TFTP directory of the LAVA instance which can be specified by `--tftp-dir` in lavabo-server. We use SFTP protocol to perform this task. Thus, we can access from the board the files we need on LAVA instance TFTP server under a subdirectory named after the username specified with each SSH key.

### How to enable autocompletion?

- Bash
Add `eval "$(register-python-argcomplete lavabo)"` to your .bashrc.

- Zsh
Add to your .zshrc:
```
autoload -U +X compinit && compinit
autoload -U +X bashcompinit && bashcompinit
eval "$(register-python-argcomplete lavabo)"
```

Source: http://argcomplete.readthedocs.io/en/latest/#synopsis
