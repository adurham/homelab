#! /usr/bin/env python
from __future__ import division
from __future__ import print_function
import sys
sys.dont_write_bytecode = True

# Python v2 and v3 compatibility
PY2 = sys.version_info[0] == 2
PY3 = sys.version_info[0] == 3
if PY2:
    from urllib2 import URLError
    from urllib2 import HTTPError
    from urllib2 import urlopen
    from urllib2 import Request as url_request
    from StringIO import StringIO
    from urlparse import urlparse
elif PY3:
    long = int
    from urllib.error import URLError
    from urllib.error import HTTPError
    from urllib.request import urlopen
    from urllib.request import Request as url_request
    from io import StringIO
    from urllib.parse import urlparse
else:
    msg = "Don't know how to run on Python v{0}.{1}."
    raise NotImplementedError(msg.format(sys.version_info))

import time
import os.path
import argparse
import xml.dom.minidom
import xml.etree.ElementTree as ET
from datetime import datetime

# The command-line parser here at the top should give the reader an idea of how
# this tool should be used.
#
# TO-DO: Add a purge command that will remove orphaned /Download/SHA-256 files.
def command_line_parser():
    # The main parser
    ap = argparse.ArgumentParser(
        description = "Manage endpoint Client API downloads.",
        epilog="."
    )
    subparsers = ap.add_subparsers(
        title=None,
        dest="command",
        metavar="download | monitor | cancel",
    )

    # The "download" command options
    dld_parser = subparsers.add_parser(
        "download", help="Request a URL to download.",
        epilog="Provide a URL do download to the Client."
    )
    dld_parser.add_argument(
        "-verbose",
        help="Print verbose request and reply messages XML.",
        required=False,
        default=False,
        action="store_true"
    )
    dld_parser.add_argument(
        "-interval",
        help="The monitoring interval in seconds. " \
        "Use zero to disable monitoring the request.",
        required=False,
        default=30,
        type=float,
        metavar="Seconds"
    )
    dld_parser.add_argument(
        "-timeout",
        help="Timeout the download after this many seconds.",
        metavar="Seconds",
        default=3600
    )
    dld_parser.add_argument(
        "-force",
        help="Force a download by removing the target file first (PLAT-10429).",
        dest="force",
        action="store_true",
        default=False
    )
    dld_parser.add_argument(
        "URLs",
        help="A URL to download.",
        metavar="URL",
        nargs='+'
    )

    # Set the "monitor" command options
    mon_parser = subparsers.add_parser(
        "monitor",
        help="Monitor outstanding downloads on the Client API.",
        epilog="Monitor the download status of active Client API downloads.",
    )
    mon_parser.add_argument(
        "-verbose",
        help="Print verbose request and reply messages XML.",
        required=False,
        default=False,
        action="store_true"
    )
    mon_parser.add_argument(
        "-interval",
        help="The monitoring interval in seconds. " \
        "Use zero to check the request only once.",
        required=False,
        default=30,
        type=float,
        metavar="Seconds"
    )
    mon_parser.add_argument(
        "-omit-completed",
        help="Omit displaying already completed requests.",
        required=False,
        default=False,
        action="store_true"
    )
    mon_parser.add_argument(
        "URLs",
        help="Specify which URLs to monitor.",
        metavar="URL",
        nargs="*"
    )

    # Set the "cancel" command options
    rm_parser = subparsers.add_parser(
        "cancel", help="Cancel one or more outstanding download requests.",
        epilog="This command will cancel one or more outstanding download " \
        "requests."
    )
    rm_parser.add_argument(
        "-verbose",
        help="Print verbose request and reply message XML.",
        required=False,
        default=False,
        action="store_true"
    )
    rm_parser.add_argument(
        "-interval",
        help="The monitoring interval in seconds. " \
        "Use zero to disable monitoring the request.",
        required=False,
        default=30,
        type=float,
        metavar="Seconds"
    )
    rm_parser.add_argument(
        "URLs",
        help="One or more URL requests to be canceled.",
        metavar="URLs",
        nargs="+"
    )

    return ap

class PrettyPrintET(ET.ElementTree):
    def pretty_print(self):
        return xml.dom.minidom.parseString(
            ET.tostring(self.getroot())
        ).toprettyxml(indent=" "*3, newl="\n     ")

# Setup Tanium Server HTTPs request tools
import ssl
# SSL context for urlopen -> TS queries
ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
ssl_ctx.verify_flags = ssl.CERT_NONE
ssl_ctx.check_hostname = False

def tc_api_request(xml_et, verbose=False):
    """
    Make an HTTPs request to the local Tanium Client API.
    """
    # The request will always be to the local-host
    req = url_request("http://127.0.0.1:17473")
    req.get_method = lambda: 'POST'

    xml_data = ET.tostring(xml_et.getroot(), method="xml")
    if verbose is True:
        print("\nRequest:\n{0}".format(xml_et.pretty_print()))
    reply = urlopen(req, data=xml_data, context=ssl_ctx)
    reply_data = reply.read().decode()
    ret = PrettyPrintET()
    ret.parse(StringIO(reply_data))
    if verbose is True:
        print("\nReply:\n{0}".format(ret.pretty_print()))

    return ret

def tc_path(opts):
    """
    This script must be placed in the Tanium Client installation directory.
    ... because I'm lazy to go hunt in the Windows registry.
    """
    tc_dir = os.path.dirname(os.path.realpath(__file__))
    # Test for the existence of a TaniumClient or TaniumClient.exe file
    if os.path.isfile("TaniumClient"):
        tc_file = os.path.join(tc_dir, "TaniumClient")
    elif os.path.isfile("TaniumClient.exe"):
        tc_file = os.path.join(tc_dir, "TaniumClient.exe")
    else:
        msg = "You must put this script in the Tanium Client directory"
        raise ValueError(msg)
    return tc_dir

def soap_session(opts):
    soap_session_path = os.path.join(opts.tc_path, "soap_session")
    if not os.path.isfile(soap_session_path): return None
    with open(soap_session_path, "r") as f:
        return f.read().strip()

BASE_REQ = """
<soapenv:Envelope
 xmlns:urn="urn:TaniumSOAP"
 xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">
  <soapenv:Header/>
  <soapenv:Body>
    <urn:tanium_soap_request>
      <session />       <!-- The request session goes here -->
      <command />       <!-- The request command goes here -->
      <object_list />   <!-- The request object_list goes here -->
    </urn:tanium_soap_request>
  </soapenv:Body>
</soapenv:Envelope>
"""
def base_xml(opts):
    base = PrettyPrintET()
    base.parse(StringIO(BASE_REQ))
    # Add the soap_session token value
    soap_session_token = soap_session(opts)
    if soap_session_token is not None:
        base.find(".//session").text = soap_session_token
    return base

def _add_objects(base, opts):
    obj_l = base.find(".//object_list")
    for url in opts.URLs:
        new_dld = ET.fromstring("<download />")
        new_url = ET.fromstring("<url>{0}</url>".format(url))
        new_dld.append(new_url)
        # The <name> derived from the URL
        f_name = urlparse(url).path.split("/")[-1]
        name_et = ET.fromstring("<name>{}</name>".format(f_name))
        new_dld.append(name_et)

        # Add the download to the list for the request
        obj_l.append(new_dld)

def download_xml(opts):
    base = base_xml(opts)
    base.find(".//command").text = "AddObject"
    # Add the URLs
    _add_objects(base, opts)
    return base

def monitor_xml(opts):
    base = base_xml(opts)
    base.find(".//command").text = "GetObject"
    # Add the URLs
    _add_objects(base, opts)
    return base

def cancel_xml(opts):
    base = base_xml(opts)
    base.find(".//command").text = "DeleteObject"
    # Add the URLs
    _add_objects(base, opts)
    return base
    
def validate_command_line(opts):
    """
    Make sure the target directory is indeed a directory and that our running
    process has the same effective user ID as the owner of the target.
    """
    opts.tc_path = tc_path(opts)

    if not opts.URLs:
        opts.URLs = [""]
    else:
        # Make all URLs have an actual path
        for url in opts.URLs:
            f_name = urlparse(url).path.split("/")[-1]
            if not f_name or f_name.isspace():
                msg = "URLs must have a path and not just a server name: {}"
                raise ValueError(msg.format(url))

    # Tracking already completed URL requests
    try: opts.omit_completed
    except AttributeError: opts.omit_completed = False
    finally: opts.seen_completed = {}

def report_result(reply):
    first = True
    all_completed = True
    for dld in reply.find(".//result_object").findall(".//download"):
        # The datas from the reply XML
        url = dld.find(".//url").text
        name = dld.find(".//name").text
        try: path = dld.find(".//path").text
        except AttributeError: path = "N/A"
        try: status = dld.find(".//status").text
        except AttributeError: status = "N/A"

        # Don't report on already Completed requests if opts.omit_completed
        if status == "Completed":
            if url in opts.seen_completed and opts.omit_completed is True:
                continue
            # Just note that this has URL has completed now
            opts.seen_completed[url] = True

        # Just separate pretty
        if first is False: print("")
        else: first = False

        # The download status
        print("    URL: {0}".format(url))
        print("   Name: {0}".format(name))
        print("   Path: {0}".format(path))
        print(" Status: {0}".format(status))

        # Check whether this one is completed
        if "Completed" != status: all_completed = False

    return all_completed

def download_command(opts):
    req = download_xml(opts)

    # For each download we should have a <timeout_seconds>
    to_et = ET.fromstring(
        "<timeout_seconds>{0}</timeout_seconds>".format(opts.timeout)
    )
    for dld_et in req.findall(".//download"):
        dld_et.append(to_et)
        # For -force downloads remove the target file
        if opts.force:
            f_name = dld_et.find("./name").text
            try: os.unlink(os.path.join(opts.tc_path, "Downloads", f_name))
            except OSError as e: pass

    rep = tc_api_request(req, verbose=opts.verbose)
    report_result(rep)

    # And keep monitoring
    if opts.interval > 0: monitor_command(opts)

def monitor_command(opts):
    while True:
        try:
            print("\n[{0}] Monitoring".format(datetime.now().isoformat()))
            req = monitor_xml(opts)
            rep = tc_api_request(req, verbose=opts.verbose)
            if report_result(rep) is True: break
            if opts.interval > 0: time.sleep(opts.interval)
            else: break
        except KeyboardInterrupt:
            print("\n\nExiting")
            break

def cancel_command(opts):
    req = cancel_xml(opts)
    rep = tc_api_request(req, verbose=opts.verbose)
    report_result(rep)

    # And keep monitoring
    if opts.interval > 0: monitor_command(opts)

if __name__ == "__main__":
    opts_parser = command_line_parser()
    # Parse and validate
    opts = opts_parser.parse_args()
    validate_command_line(opts)
    print("Opts: {0}".format(opts))

    # Run them commands
    if opts.command == "download": download_command(opts)
    elif opts.command == "monitor": monitor_command(opts)
    elif opts.command == "cancel": cancel_command(opts)
    print("")
