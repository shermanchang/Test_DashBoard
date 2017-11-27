#!/usr/bin/python

import sys, os, time, textfsm, threading, SocketServer, sqlite3, hashlib, logging, logging.handlers, re, optparse

root_dir = os.path.join(os.path.dirname(__file__))
__version__ = "version 2.0.0"
__logfile__ = os.path.join(root_dir, "CCDServer.log")
__db__ = ""

lock = threading.Lock()

class ThreadedTCPRequestHandler(SocketServer.BaseRequestHandler):

    def recv_data(self):
        raw_data = ""
        while True:
            data = self.request.recv(1024)
            if not data:
                break
            raw_data += data
        return raw_data

    def check_data_type(self, data):
        """
        return the app and dashboard that msg is related too based on formatted first line
        :param data to check
        :return: app and dashboard or None if inconsistent value
        """
        app = ''
        dashboard = ''
        data_type = data.split('\n', 1)[0].split('/')
        if data_type[0].lower() == "dashboard" and len(data_type) >= 3:
            app = data_type[1]
            dashboard = data_type[2]

        if app != 'pts' or (dashboard != 'treatment' and dashboard != 'tcs'):
            logging.error("Unknown data type %s" % data_type)
            return

        logging.debug("data_type: %s %s" % (app, dashboard))
        return app, dashboard

    def calculate_cksum(self, msg):
        if msg:
            cksum = hashlib.md5(msg).hexdigest()
            logging.debug("checksum: %s" % str(cksum))
            return cksum
        else:
            logging.debug("no checksum")
            return

    def extract_section(self, section, raw_data):
        logging.debug("section: %s" % section)
        section_msg = re.search(section + "(:\{.*?\s\}\s)", raw_data, re.DOTALL)
        logging.debug("section body: %s" % section_msg)
        if section_msg:
            return section_msg.group()
        else:
            return

    def parse_data(self, section, raw_text_data):

        section_template = os.path.join(root_dir, 'templates/template_' + section)
        with open(section_template) as template:
            re_table = textfsm.TextFSM(template)
            data = re_table.ParseText(raw_text_data)

        logging.debug("data: %s" % data)
        return data

    def handle(self):

        msg = self.recv_data()

        client_id = self.client_address[0].rsplit('.', 1)[0]
        client_id = client_id[:-1]

        #logging.debug("client ip: %s" % self.client_address)
        logging.debug("client id: %s" % client_id)
        logging.debug("raw_data:\n%s" % msg)

        if msg == "":
            logging.error("Nothing received from %s" % self.client_address)
            return

        data_type = self.check_data_type(msg)
        if not data_type:
            logging.error("Inconsistent data type %s" % data_type)
            return

        app, dashboard = data_type

        new_cksum = self.calculate_cksum(msg)

        print("check current client_id checksum for that dashboard")
        old_cksum = 0
        print("error is unknown client_id or empty checksum")

        if new_cksum != old_cksum:

            for section in ["TCS", "OIS", "PCVUE", "PPVS", "IT"]:

                section_body = self.extract_section(section, msg)
                new_section_cksum = self.calculate_cksum(section_body)
                print("check current client_id section checksum for that dashboard")
                old_section_cksum = 0

                if new_section_cksum != old_section_cksum:
                    data = self.parse_data(section, section_body)
                    print("update data to DB")

        logging.info("update freshness for %s, %s" % (client_id, dashboard))
        print("update timestamp for client_id for that dashboard")

class ThreadedTCPServer(SocketServer.ThreadingMixIn, SocketServer.TCPServer):
    pass

if __name__ == "__main__":
    parser = optparse.OptionParser("usage: %prog [options]", version="version = %s" % __version__)
    parser.add_option("-i", "--hostname", metavar="HOST", help="set server hostname")
    parser.add_option("-p", "--port", metavar="PORT", help="set server port")
    parser.add_option("-d", "--database", metavar="DB", help="set sqlite database to use")
    parser.add_option("-u", "--username", metavar="USERNAME", help="set SVN username")
    parser.add_option("-w", "--password", metavar="PASSWORD", help="set SVN password")
    (options, args) = parser.parse_args()
    logger = logging.getLogger()
    rfh = logging.handlers.RotatingFileHandler(__logfile__, maxBytes=10 * 1024 * 1024, backupCount=3)
    sh = logging.StreamHandler()
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s %(name)-12s %(threadName)s: %(levelname)-8s %(message)s')
    rfh.setFormatter(formatter)
    sh.setFormatter(formatter)
    logger.addHandler(rfh)
    logger.addHandler(sh)

    if options.hostname and options.port and options.database:
        HOST, PORT, DB = options.hostname, int(options.port), options.database
    else:
        parser.error("define options --hostname, --port and --database")
        sys.exit(2)

    server = ThreadedTCPServer((HOST, PORT), ThreadedTCPRequestHandler)
    __db__ = os.path.join(root_dir, DB)
    logging.info("script version - %s" % __version__)
    logging.info(__db__)
    logging.info(__logfile__)
    logging.info("starting up on %s port %s" % server.server_address)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    logging.info("Server loop running in thread:%s" % server_thread.name)

    while True:
        time.sleep(1)

    server.shutdown()
    sys.exit(0)
