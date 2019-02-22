#!/usr/bin/env python3
import os
import sys
import signal
import time
import calendar
import configparser
import tempfile
from datetime import datetime
import urllib.request
import xml.etree.ElementTree
from threading import Thread
try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO

import manhole
manhole.install()

# clear terminal for writing
os.system('clear')

# read initial configuration options from file
parser = configparser.RawConfigParser()
config_path = os.path.dirname(os.path.realpath(__file__)) + '/transit-times.conf'
parser.read(config_path)
loglevel = parser.get('DEFAULT', 'loglevel')

app_id = parser.get('DEFAULT', 'app_id')
train_stop = parser.get('TRAINS', 'train_stop')
bus_stops = [x.strip() for x in parser.get('BUSES', 'bus_stops').split(',')]

arrivals_arr = []
arrivals_const = []

# track whether data gathering is in an error state
errstate = False

# create temp file to hold bash script for printing
tf = tempfile.NamedTemporaryFile(delete=False)
tfile = tf.name
tf.write(b'HOME=$(tput cup 0 0)\n')
tf.write(b'ED=$(tput ed)\n')
tf.write(b'EL=$(tput el)\n')
tf.write(b'COLS=$(tput cols)\n')
tf.write(b'CONTENTS=$(echo -e "$(cat ${1})" | awk "NF > 0" | expand -t 4 | sed "/------------------/q")$(echo ; echo -e "$(cat ${1})" | awk "NF > 0" | expand -t 4 | awk "f{print;} /---/{f=1}" | sed "s/in/in  /g")\n')
tf.write(b'while read -r LINE ;\n')
tf.write(b'do\n')
tf.write(b'''    printf '%-*.*s%s\n' ${COLS} ${COLS} "${LINE}" "${EL}"''')
tf.write(b'\n')
# tf.write(b'done <<< $(echo -e "$(cat ${1})" | awk "NF > 0" | expand -t 4)\n')
tf.write(b'done <<< "${CONTENTS}"\n')
tf.write(b'''printf '%s%s' "${ED}" "${HOME}"''')
tf.flush()
os.chmod(tfile, 0o777)  # make executable for later

# create another temp file to hold text to print
ptf = tempfile.NamedTemporaryFile(delete=False)
ptfile = ptf.name
os.chmod(tfile, 0o666)  # make universally readable for later


def logwrite(entry, loglevel_):
    try:
        logrank = {
            'ERROR': 1,
            'INFO': 2,
            'DEBUG': 3
        }
        if logrank[str(loglevel.upper())] >= logrank[str(loglevel_.upper())]:
            f = open('log', 'a')
            f.write('[ %s ] [ %s ] %s' % (datetime.now().isoformat(), loglevel_.upper(), entry,))
            f.write('\n')
            f.close()
    except KeyError:
        # unknown log level
        if loglevel.upper() == loglevel_.upper():
            f = open('log', 'a')
            f.write('[ %s ] [ %s ] %s' % (datetime.now().isoformat(), loglevel_.upper(), entry,))
            f.write('\n')
            f.close()


class arrival:
    def __init__(self, is_bus, is_delayed, line_id, arrival_time):
        self.is_bus = is_bus
        self.is_delayed = is_delayed
        self.line_id = line_id
        self.arrival_time = arrival_time


def get_stop_data(stop_id):
    arrivals_url = 'http://developer.trimet.org/ws/V1/arrivals/locIDs/' + str(stop_id) + '/appID/' + str(app_id)
    with urllib.request.urlopen(arrivals_url) as arrivals_reader:
        try:
            arrivals_data = arrivals_reader.read()
        except IOError:
            logwrite("network err", 'ERROR')
            exit(1)
        if len(arrivals_data) == 0:
            logwrite("data err", 'ERROR')
            exit(1)
        return arrivals_data


def get_train_data(stop_id):
    arrivals_data = get_stop_data(stop_id)
    arrivals_tree = xml.etree.ElementTree.parse(StringIO(arrivals_data.decode('utf-8')))
    for node in arrivals_tree.findall('.//{urn:trimet:arrivals}arrival'):
        arrival_time = None
        # get line type
        if "Red Line" in node.attrib['fullSign']:
            line_color = "red"
        else:
            line_color = "blue"
        # get status and arrival time
        if node.attrib['status'] == "cancelled":
            is_delayed = "cancelled"
        elif node.attrib['status'] == "delayed":
            is_delayed = "delayed"
        else:
            is_delayed = "on time"
            try:
                arrival_time = int(node.attrib['estimated'])
            except KeyError:
                arrival_time = int(node.attrib['scheduled'])
            except Exception as e:
                logwrite("uncaught exception:\n%s" % (e,), 'ERROR')
                exit(1)
        # add to arrival times array
        arrivals_arr.append(arrival(is_bus = "no", is_delayed = is_delayed, line_id = line_color, arrival_time = arrival_time))


def get_bus_data(stop_id):
    arrivals_data = get_stop_data(stop_id)
    arrivals_tree = xml.etree.ElementTree.parse(StringIO(arrivals_data.decode('utf-8')))
    for node in arrivals_tree.findall('.//{urn:trimet:arrivals}arrival'):
        arrival_time = None
        # get status and arrival time
        if node.attrib['status'] == "cancelled":
            is_delayed = "cancelled"
        elif node.attrib['status'] == "delayed":
            is_delayed = "delayed"
        elif node.attrib['status'] == "estimated":
            is_delayed = "on time"
            arrival_time = int(node.attrib['estimated'])
        else:  # node.attrib["status"] = "scheduled"
            is_delayed = "on time"
            arrival_time = int(node.attrib['scheduled'])
            # add to arrival times array
        bus_line = int(node.attrib['route'])
        arrivals_arr.append(arrival(is_bus = "yes", is_delayed = is_delayed, line_id = bus_line, arrival_time = arrival_time))


# def update_times():
#     while True:
#         global update_times_running
#         global arrivals_const
#         arrivals_const = arrivals_arr.copy()
#         update_times_running = True
#         del arrivals_arr[:]
#         logwrite("getting train data for stop %s" % (train_stop,), "INFO")
#         get_train_data(train_stop)
#         for bus in bus_stops:
#             logwrite("getting bus data for stop %s" % (bus,), "INFO")
#             get_bus_data(bus)
#         update_times_running = False
#         time.sleep(10)


def update_times():
    while True:
        global update_times_running
        global arrivals_const
        arrivals_const = arrivals_arr.copy()
        update_times_running = True
        del arrivals_arr[:]
        logwrite("getting train data for stop %s" % (train_stop,), "INFO")
        try:
            get_train_data(train_stop)
            for bus in bus_stops:
                logwrite("getting bus data for stop %s" % (bus,), "INFO")
                get_bus_data(bus)
            errstate = False
        except Exception as err:
            logwrite("exception encountered doing update_times!", "ERROR")
            logwrite(str(err), "ERROR")
            errstate = True
        update_times_running = False
        time.sleep(10)


def update_display():
    global update_times_running
    global arrivals_arr
    global arrivals_const
    while True:
        # make sure we aren't in an error state, and print message if we are
        if errstate:
            os.system('clear')
            print('error encountered getting arrival data!')
            print('check log for more info')
        else:
            # decide whether to use arrivals_arr or arrivals_const depending on whether update_times is running
            if update_times_running:
                logwrite("update_times is running, using arrivals_const instead of arrivals_arr", "DEBUG")
                logwrite("arrivals_const data: %s" % (arrivals_const,), "DEBUG")
                logwrite(dir(arrivals_const), "DEBUG")
                logwrite("".join([str(x) for x in arrivals_const]), "DEBUG")
                use_arr = arrivals_const.copy()
            else:
                use_arr = arrivals_arr
            starttime = time.time()
            printstring = ""
            # train times
            printstring = "next trains:\n"
            for arr in use_arr:
                h = 0
                m = 0
                s = 0
                if arr.is_bus == "no":
                    # train found
                    line_color = arr.line_id
                    if line_color == "red":
                        printstring += ('\033[1;31m' + 'red' + '\033[1;37m' + ' line ')
                    else:
                        printstring += ('\033[1;34m' + 'blue' + '\033[1;37m' + ' line ')
                    if arr.is_delayed == "cancelled":
                        printstring += "in\t(CANCELLED)\n"
                    elif arr.is_delayed == "delayed":
                        printstring += "in\t(DELAYED)\n"
                    elif (arr.arrival_time / 1000) < calendar.timegm(time.gmtime()):
                        printstring += "in\t(ARRIVED)\n"
                    else:
                        # on time
                        m, s = divmod((int(int(arr.arrival_time) / 1000) - int(calendar.timegm(time.gmtime()))), 60)
                        if m > 59:
                            h, m = divmod(m, 60)
                        printstring += 'in\t'
                        if h != 0:
                            printstring += str(h)
                            printstring += ":"
                            if len(str(m)) == 1:
                                printstring += "0"
                        printstring += str(m)
                        printstring += ":"
                        if len(str(s)) == 1:
                            printstring += "0"
                        printstring += str(s)
                        printstring += '\n'
            # separator
            printstring += '------------------\n'
            # bus times
            printstring += "next buses:\n"
            for arr in use_arr:
                h = 0
                m = 0
                s = 0
                if arr.is_bus == "yes":
                    printstring += "#"
                    printstring += str(arr.line_id)
                    printstring += " "
                    if arr.is_delayed == "cancelled":
                        printstring += "in\t\t(CANCELLED)\n"
                    elif arr.is_delayed == "delayed":
                        printstring += "in\t\t(DELAYED)\n"
                    elif (arr.arrival_time / 1000) < calendar.timegm(time.gmtime()):
                        printstring += "in\t\t(ARRIVED)\n"
                    else:
                        # on time
                        m, s = divmod((int(int(arr.arrival_time) / 1000) - int(calendar.timegm(time.gmtime()))), 60)
                        if m > 59:
                            h, m = divmod(m, 60)
                        printstring += 'in\t\t'
                        if h != 0:
                            printstring += str(h)
                            printstring += ":"
                            if len(str(m)) == 1:
                                printstring += "0"
                        printstring += str(m)
                        printstring += ":"
                        if len(str(s)) == 1:
                            printstring += "0"
                        printstring += str(s)
                        printstring += "\n"
            # wipe screen then write
            execstring = 'bash ' + tfile + ' ' + ptfile
            ptf.seek(0)
            ptf.truncate()  # clear file before writing new contents to write to terminal
            ptf.write(str.encode(printstring))
            ptf.flush()
            os.system(execstring)
            # sleep (1 - execution time) seconds
            time.sleep(1.0 - ((time.time() - starttime) % 60.0))


def main():
    logwrite("starting trimet_times.py", "INFO")
    global update_times_running
    Thread(target = update_times).start()
    time.sleep(4)
    Thread(target = update_display).start()


def signal_handler(sig, frame):
    tf.close()
    ptf.close()
    os.unlink(tfile)
    os.unlink(ptfile)
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)

if __name__ ==  '__main__':
    main()
