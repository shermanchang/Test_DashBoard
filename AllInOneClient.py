"""
# 1. get the version file path from config file
# 2. get the usefully information from version files
# 3. combine the content and send out to server
"""

import os
import sys
import socket
import dicom
import subprocess
import random
import time
import fnmatch
import glob
import xml.etree.ElementTree
import re


class Agent:
    """
    Class to parse app's version files, and collect IT information
    """
    def __init__(self, usr, app):
        self.user = usr
        self.apps = app
        self.data = ""

    def get_files(self, path, ext):
        """
        Find files with specified extension
        Args:
            path: path to be searched in
            ext: file extension
        Returns:
            A list of target files
        """
        file_list = []
        for filename in os.listdir(path):
            fp = os.path.join(path, filename)
            if os.path.isfile(fp) and fnmatch.fnmatch(filename, ext):
                file_list.append(fp)
        return file_list

    def delete_file(self, file_path):
        """
        Remove file
        Args:
            file_path: file path
        """
        try:
            os.remove(file_path)
        except:
            pass

    def get_command_result(self, cmd):
        """
        Return the result of a linux command
        Args:
            cmd: linux command
        Returns:
            The result of the command; if error occurs, return a null string
        """
        command = cmd.split(' ')
        try:
            result = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True).communicate()[0]
            return result.strip('\n').replace("\n", "; ")
        except:
            return ''

    def get_command_return_code(self, cmd):
        """
        Return the return code of a linux command
        Args:
            cmd: linux command
        Returns:
            The return code of the command, or None if another error
        """
        command = cmd.split(' ')
        try:
            p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            output, error = p.communicate()
            return p.returncode
        except:
            return None

    def get_java_version(self, target):
        """
        Get the java version of specified machine
        Args:
            target: hostname of target machine
        Returns:
            The java version; if error occurs, return a null string
        """
        cmd = "ssh -o BatchMode=yes {0} /opt/java1.8/bin/java -version".format(target)
        return self.get_command_result(cmd)

    def get_psql_version(self, target):
        """
        Get the PostgresSQL version of specified machine
        Args:
            target: hostname of target machine
        Returns:
            The PostgresSQL version; if error occurs, return a null string
        """
        cmd = "ssh -o BatchMode=yes {0} psql --version".format(target)
        return self.get_command_result(cmd)

    def get_os_version(self, target):
        """
        Get the OS version of specified machine
        Args:
            target: hostname of target machine
        Returns:
            The OS version; if error occurs, return a null string
        """
        cmd = "ssh -o BatchMode=yes {0} cat /etc/os-release".format(target)
        res = self.get_command_result(cmd)
        if res == "":
            cmd = "ssh -o BatchMode=yes {0} cat /etc/SuSE-release".format(target)
            res = self.get_command_result(cmd)
        return res

    def get_kernel_version(self, target):
        """
        Get the kernel version of specified machine
        Args:
            target: hostname of target machine
        Returns:
            The kernel version; if error occurs, return a null string
        """
        cmd = "ssh -o BatchMode=yes {0} /bin/uname -a".format(target)
        return self.get_command_result(cmd)

    def check_online(self, target):
        """
        Check if the target is communicable
        Args:
            target: hostname of target machine
        Returns:
            If the target can ping, return True; else return False
        """
        cmd = "ping {0} -c 1 -W 1".format(target)
        if self.get_command_return_code(cmd) == 0:
            return True
        else:
            return False

    def collect_IT(self):
        """
        Collecting IT related data
        """
        self.data += "MCR PythonVersion:" + sys.version.replace('\n', ' ').strip() + '\n'

        machines = []

        if self.check_online('mcrs3'):
            machines.append('mcrs3')

        if self.check_online('mcrw1'):
            machines.append('mcrw1')

        for i in range(6):
            tcr = "tcrw" + str(i + 1)
            if self.check_online(tcr):
                machines.append(tcr)
            pcu = "pcu" + str(i + 1)
            if self.check_online(pcu):
                machines.append(pcu)

        for mac in machines:
            if mac == 'mcrs3':
                self.data += mac.upper() + " PostgreSQLVersion:" + self.get_psql_version(mac) + '\n'

            if mac.startswith('mcr') or mac.startswith('tcr'):
                self.data += mac.upper() + " JavaVersion:" + self.get_java_version(mac) + '\n'

            self.data += mac.upper() + " OSVersion:" + self.get_os_version(mac) + '\n'
            self.data += mac.upper() + " KernelVersion:" + self.get_kernel_version(mac) + '\n'

    def parse_dcm(self, path):
        """
        Parse dicom file to get OIS information
        Args:
            path: the dicom file path
        """
        dir_list = [dir for dir in os.listdir(path) if os.path.isdir(os.path.join(path, dir))]
        dir_list.sort(key=lambda dir: os.path.getmtime(os.path.join(path, dir)))
        for i in range(10):
            if dir_list:
                latest_dir = dir_list.pop()
                list_of_files = glob.glob(os.path.join(path, latest_dir, 'RN*.dcm'))
                if list_of_files:
                    latest_file = max(list_of_files, key=os.path.getmtime)
                    try:
                        plan = dicom.read_file(latest_file)
                        if plan[0x0008, 0x0060].value == 'RTPLAN':
                            self.data += "OISType" + ":" + plan[0x0008, 0x0070].value + "\n" + \
                                    "OISVersion" + ":" + plan[0x0018, 0x1020].value + "\n"
                            break
                    except:
                        pass
            else:
                return

    def get_child_text(self, element, child):
        """
        Get the text of a xml element's child
        Args:
            element: the target element
            child: the name of child
        Returns:
            The text of the element's child or None if the element or its child is invalid
        """
        if xml.etree.ElementTree.iselement(element):
            ele = element.find(child)
            if ele is not None:
                return ele.text

        return None

    def extract_room_number(self, filename):
        """
        :param filename:
        :return: the room number or None if not room number extracted
        """
        f = os.path.basename(filename)
        room_number = re.search("PPVS0(\d).+", f)
        if room_number and len(room_number.group()) >= 1:
            return room_number.group(1)

    def parse_ppvs(self, path):
        """
        Parse ppvs version files
        Args:
            path: the xml or txt file path
        """
        for fl in self.get_files(path, "*.xml"):
            try:
                tree = xml.etree.ElementTree.parse(fl)
            except xml.etree.ElementTree.ParseError:
                continue

            root = tree.getroot()
            if root.tag != "version":
                root = root.find('version')
                if root is None:
                    continue

            room_num = self.get_child_text(root, 'room_number')
            if room_num is None or room_num != self.extract_room_number(fl):
                continue

            version = self.get_child_text(root, 'adapt_insight_version')
            cfg_ver = self.get_child_text(root, 'configuration_version')
            if version:
                self.data += "PPVS" + room_num + "Version:" + str(version) + '\n'
            if cfg_ver:
                self.data += "PPVS" + room_num + "ConfigVersion:" + str(cfg_ver) + '\n'
            if version or cfg_ver:
                if self.user == "treatment":
                    self.delete_file(fl)

        for tf in self.get_files(path, "*.txt"):
            with open(tf) as f:
                l = f.read()
                version_re = re.search("(\d+\.\d+\.\w+)", l)
                room_num = self.extract_room_number(tf)
                if version_re and len(version_re.group()) >= 1 and room_num:
                    version = version_re.group(1)
                    self.data += "PPVS" + room_num + "Version:" + version + '\n'
                    if self.user == "treatment":
                        self.delete_file(tf)

    def parse_pcvue(self, path):
        """
        Parse pcvue version file
        Args:
            path: the pcvue version file path
        """
        with open(path) as f:
            con = f.read()
            ver = re.search("(\d+\.\d+\.\w+)", con)
            if ver and len(ver.group()) >= 1:
                self.data += "PCVUE Version:" + ver.group(1) + '\n'
                if self.user == "treatment":
                    self.delete_file(path)

    def parse_apps(self):
        """
        Parse each app's version information, collect IT information
        """
        for key, value in self.apps.items():
            self.data += key + ":{\n"
            if key == "TCS":
                with open(value, 'r') as f:
                    con = f.read()
                    self.data += con
            elif key == "OIS":
                self.parse_dcm(value)
            elif key == "PPVS":
                self.parse_ppvs(value)
            elif key == "PCVUE":
                self.parse_pcvue(value)
            elif key == "IT":
                self.collect_IT()
            self.data += "}\n"


class Client:
    """
    Class to connect to server and sent data
    """
    def __init__(self):
        self.sock = None
        self.server_address = (sys.argv[1], int(sys.argv[2]))

    def connect(self):
        """
        connect to server
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(self.server_address)
        self.sock = sock

    def send(self, data):
        """
        send data to server
        """
        try:
            self.sock.sendall(data)
        finally:
            self.sock.close()


if __name__ == "__main__":
    if len(sys.argv) is not 4:
        print("Usage: python AllInOneClient.py hostname port dashboard/pts/user")
        print("Example: python AllInOneClient.py server.lln.iba 5555 dashboard/pts/tcs")
        sys.exit(1)

    # Wait a random time between 0 and 1s to avoid flooding server with sync request
    time.sleep(random.random())

    user = sys.argv[3].split('/', 3)[2]
    apps = {}
    user_path = os.path.join("/TCS/runtimeStore", user)
    TCS = os.path.join(user_path, "runtime/TCSversion")
    if os.path.isfile(TCS):
        apps["TCS"] = TCS

        with open(TCS, 'r') as fl:
            for line in fl:
                if "PTS DB:" in line:
                    DB_NAME = line.split(':', 2)[1].strip()

        OIS = user_path + "/workspace/runtime/tsmFiles/" + "mcrs3_" + DB_NAME + "/Inbox"
        if os.path.isdir(OIS):
            apps["OIS"] = OIS

    PPVS = "/srv/ftp/keystone_public/aidm"
    if os.path.isdir(PPVS):
        if glob.glob(os.path.join(PPVS, '*.xml')) or glob.glob(os.path.join(PPVS, '*.txt')):
            apps["PPVS"] = PPVS

    PCVUE = "/srv/ftp/keystone_public/vtt/version.pcv"
    if os.path.isfile(PCVUE):
        apps["PCVUE"] = PCVUE

    apps["IT"] = ""

    a = Agent(user, apps)
    a.parse_apps()
    c = Client()
    c.connect()
    c.send(sys.argv[3] + "\n" + a.data)
