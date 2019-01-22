#!/usr/bin/env python3
import os
import sys
import time
import calendar
from datetime import datetime
import urllib.request
import xml.etree.ElementTree
from threading import Thread
try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO

#read initial configuration options from file
import configparser
parser = configparser.RawConfigParser()
config_path = os.path.dirname(os.path.realpath(__file__)) + '/transit-times.conf'
parser.read(config_path)
loglevel = parser.get('DEFAULT', 'loglevel')

app_id = parser.get('DEFAULT', 'app_id')
train_stop = parser.get('TRAINS', 'train_stop')
bus_stops = [ x.strip() for x in parser.get('BUSES', 'bus_stops').split(',')]

arrivals_arr = []

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
    except KeyError as e:
        #unknown log level
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
    with  urllib.request.urlopen(arrivals_url) as arrivals_reader:
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
        #get line type
        if "Red Line" in node.attrib['fullSign']:
            line_color = "red"
        else:
            line_color = "blue"
        #get status and arrival time
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
        #add to arrival times array
        arrivals_arr.append(arrival(is_bus = "no", is_delayed = is_delayed, line_id = line_color, arrival_time = arrival_time))

def get_bus_data(stop_id):
    arrivals_data = get_stop_data(stop_id)
    arrivals_tree = xml.etree.ElementTree.parse(StringIO(arrivals_data.decode('utf-8')))
    for node in arrivals_tree.findall('.//{urn:trimet:arrivals}arrival'):
        arrival_time = None
        #get status and arrival time
        if node.attrib['status'] == "cancelled":
            is_delayed = "cancelled"
        elif node.attrib['status'] == "delayed":
            is_delayed = "delayed"
        elif node.attrib['status'] == "estimated":
            is_delayed = "on time"
            arrival_time = int(node.attrib['estimated'])
        else: # node.attrib["status"] = "scheduled"
            is_delayed = "on time"
            arrival_time = int(node.attrib['scheduled'])
            #add to arrival times array
        bus_line = int(node.attrib['route'])
        arrivals_arr.append(arrival(is_bus = "yes", is_delayed = is_delayed, line_id = bus_line, arrival_time = arrival_time))

def update_times():
    while True:
        del arrivals_arr[:]
        logwrite("getting train data for stop %s" % (train_stop,), "INFO")
        get_train_data(train_stop)
        for bus in bus_stops:
            logwrite("getting bus data for stop %s" % (bus,), "INFO")
            get_bus_data(bus)
        time.sleep(10)

def update_display():
    while True:
        starttime=time.time()
        printstring = ""
        #train times
        printstring = "next trains:\n"
        for arr in arrivals_arr:
            h = 0
            m = 0
            s = 0
            if arr.is_bus == "no":
                #train found
                line_color = arr.line_id
                if line_color == "red":
                    printstring += ('\033[1;31m' + 'red' + '\033[1;37m' + ' line ')
                else:
                    printstring += ('\033[1;34m' + 'blue' + '\033[1;37m' + ' line ')
                if arr.is_delayed == "cancelled":
                    printstring += "\t(CANCELLED)\n"
                elif arr.is_delayed == "delayed":
                    printstring += "\t(DELAYED)\n"
                elif (arr.arrival_time / 1000) < calendar.timegm(time.gmtime()):
                    printstring += "\tARRIVED!\n"
                else:
                    #on time
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
        #separator
        printstring += '------------------\n'
        #bus times
        printstring += "next buses:\n"
        for arr in arrivals_arr:
            h = 0
            m = 0
            s = 0
            if arr.is_bus == "yes":
                printstring += "#"
                printstring += str(arr.line_id)
                printstring += " "
                if arr.is_delayed == "cancelled":
                    printstring += "\t\t(CANCELLED)\n"
                elif arr.is_delayed == "delayed":
                    printstring += "\t\t(DELAYED)\n"
                elif (arr.arrival_time / 1000) < calendar.timegm(time.gmtime()):
                    printstring += "\t\tARRIVED!\n" 
                else:
                    #on time
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
                    printstring += '\n'
        #wipe screen then write
        os.system('clear')
        print(printstring)
        #sleep (1 - execution time) seconds
        time.sleep(1.0 - ((time.time() - starttime) % 60.0))

def main():
    Thread(target = update_times).start()
    time.sleep(4)
    Thread(target = update_display).start()

if __name__ ==  '__main__':
    main()