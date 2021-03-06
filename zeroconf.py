#!/usr/bin/env python
# coding: utf-8

"""
Simple/Pythonic Zeroconf Service Search/Registration
"""

__author__ = u"Sébastien Boisgérault <Sebastien.Boisgerault@mines-paristech.fr>"
__license__ = "MIT License"
__url__ = "https://github.com/boisgera/zeroconf" 
__version__ = "2.0.1"

# Python 2.7 Standard Library
import atexit
import pipes
import re
import subprocess
import sys
import time

if sys.platform.startswith("linux"):
    # Third-Party Libraries
    import sh
    if not sh.which("avahi-browse"):
        raise ImportError("unable to find avahi command-line tools")
elif sys.platform.startswith("win"):
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    try:
        process = subprocess.Popen("dns-sd", startupinfo=startupinfo)
        process.kill()
    except WindowsError:
        raise ImportError("unable to find dns-sd command-line tools")

# Service Search
# ------------------------------------------------------------------------------
def search(name=None, type=None, domain="local"):
    """
    Search available Zeroconf services

    The result is a dictionary with service (name, type, domain) keys 
    and data values ; data are dictionaries with "hostname", "address", 
    "port" and "txt" keys.
    """
    def name_match(service):
        name_, _, _ = service
        return (name is None or name_ == name)

    if sys.platform.startswith("linux"):

        options = {"terminate"   : True  ,
                   "resolve"     : True  ,
                   "parsable"    : True  ,
                   "no-db-lookup": True  ,
                   "domain"      : domain}
        if type:
             results = sh.avahi_browse(type, **options)
        else:
             results = sh.avahi_browse(all=True, **options)
        results = [line.split(";") for line in results.splitlines()]

        info = {}
        for result in results:
            if result[0] == "=":
                symbol, _, ip_version, name_, type_, domain_, \
                hostname, address, port, txt = result
                name_ = decode(name_)
                if ip_version == "IPv4":
                    info[(name_, type_, domain_)] = {"hostname": hostname,
                                                     "address" : address ,
                                                     "port"    : port    ,
                                                     "txt"     : txt     }



    elif sys.platform.startswith("win"):

        if not type:
            type = "_http._tcp"

        process = subprocess.Popen("dns-sd -Z " + type + " " + domain, \
                                   stdout=subprocess.PIPE, \
                                   startupinfo=startupinfo) 
        time.sleep(1.0)
        process.kill()
        results = process.stdout.read()
        results =  [line.split() for line in results.splitlines()]

        info = {}
        name_ = port = hostname = address = ""

        for result in results:
            if len(result) == 14 and result[1] == "SRV":
                name_ = decode(result[0]).split(".")[0]
                port = result[4]
                hostname = result[5]
                address = get_address(hostname)
                type_ = decode(result[0])[(decode(result[0]).find(".") + 1):]

            if len(result) == 3 and result[1] == "TXT":
                txt = str.replace(result[2],'"','')
                info[(name_, type_, domain)] = {"hostname": hostname,
                                               "address" : address ,
                                               "port"    : port    ,
                                               "txt"     : txt     }

    filtered_info = [item for item in info.items() if name_match(item[0])]
    return dict(filtered_info)

def get_address(hostname):
    process = subprocess.Popen("dns-sd -Q " + hostname,
                         stdout=subprocess.PIPE, startupinfo=startupinfo)
    time.sleep(0.1)
    process.kill()
    results = process.stdout.read()
    results =  [line.split() for line in results.splitlines()]

    if len(results) >= 1:
        return results[1][len(results[1]) - 1]
    return ''

def decode(text):
    r"""
Decode string with special characters escape sequences.

We assume that the escaping scheme follows the rules used by `avahi-browse` 
when the `--parsable` option is enabled
(see `avahi_escape_label` function in `avahi-common/domain.c`).

    >>> decode("abc")
    'abc'
    >>> decode(r"a\.c")
    'a.c'
    >>> decode(r"a\\c")
    'a\\c'
    >>> decode(r"a\032c")
    'a c'
    >>> decode(r"a\127c")
    'a\x7fc'

Characters may go beyond the 0-127 (ascii) range: 
for example, the 'RIGHT SINGLE QUOTATION MARK', 
encoded in utf-8 by the three bytes 226, 128 and 153 (decimal):

    >>> decode(r"\226\128\153")
    '\xe2\x80\x99'

Input strings in unicode are ok as long as they belong to the ascii range:

    >>> decode(ur"\226\128\153")
    '\xe2\x80\x99'
"""
    text = text.encode("ascii")
    def replace(match):
        numeric, other = match.groups()
        if numeric:
            return chr(int(numeric[1:]))
        else:
            return other[1:]

    return re.sub(r"(\\\d\d\d)|(\\.)", replace, text)

# Service Registration
# ------------------------------------------------------------------------------
_publishers = {} # service publisher processes identified by (name, type, port)

def register(name, type, port):
    """
    Register a Zeroconf service
    """
    port = str(port)
    if (name, type, port) in _publishers:
        raise RuntimeError("service already registered")
    else:
        if sys.platform.startswith("linux"):
            args = ["avahi-publish", "-s", name, type, port]
            publisher = subprocess.Popen(args, stderr=subprocess.PIPE, \
                                               stdout=subprocess.PIPE)
            _publishers[(name, type, port)] = publisher
            
        elif sys.platform.startswith("win"): 
            args = 'dns-sd -R "' + name + '" ' + type + " local " + port
            publisher = subprocess.Popen(args, stderr=subprocess.PIPE, \
                                               stdout=subprocess.PIPE, \
                                               startupinfo=startupinfo)                   
            _publishers[(name, type, port)] = publisher

def unregister(name=None, type=None, port=None):
    """
    Unregister a Zeroconf service

    When an argument is omitted, the function will attempt to unregister 
    all services that match the remaining arguments, or all services if
    no arguments are provided.
    The unregistration is limited to services whose registration comes
    from the same instance of the zeroconf module.
    """
    if port:
        port = str(port)
    pids = []
    for name_, type_, port_ in _publishers:
        if (name is None or name_ == name) and \
           (type is None or type_ == type) and \
           (port is None or port_ == port):
           pids.append((name_, type_, port_))
    for pid in pids:
        _publishers[pid].kill()
        del _publishers[pid]

atexit.register(unregister)

#-------------------------------------------------------------------------------
# Doctests
#-------------------------------------------------------------------------------
def test_basic():
    """
    >>> import time

    Register a new (fake) HTTP server
    >>> register(name="my web server", type="_http._tcp", port="49152")
    >>> time.sleep(1.0)
    
    Basic search (fully specified):
    >>> services = search("my web server", "_http._tcp", "local")
    >>> info = services.get(("my web server", "_http._tcp", "local"))
    >>> info is not None
    True
    >>> print info["port"]
    49152

    The `domain` argument is optional and defaults to "local":
    >>> search("my web server", "_http._tcp") == services
    True

    When the `type` argument is not given, all service types are considered:
    >>> search("my web server") == services
    True

    The service `name` is optional too:
    >>> http_services = search(type="_http._tcp")
    >>> services.items()[0] in http_services.items()
    True

    Unregister the HTTP server:
    >>> unregister(name="my web server", type="_http._tcp", port="49152")
    >>> time.sleep(1.0)
    >>> search("my web server", "_http._tcp")
    {}
    """

if __name__ == "__main__":
    import doctest
    doctest.testmod()
    
