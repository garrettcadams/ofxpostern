#!/usr/bin/env python

"""
OFX Test Client
"""

import json
import re
import requests
import time
from uuid import uuid4

#
# Defines
#
USER_AGENT   = 'InetClntApp/3.0'
CONTENT_TYPE = 'application/x-ofx'

HDR_OFXHEADER   = 'OFXHEADER'
HDR_DATA        = 'DATA'
HDR_VERSION     = 'VERSION'
HDR_SECURITY    = 'SECURITY'
HDR_ENCODING    = 'ENCODING'
HDR_CHARSET     = 'CHARSET'
HDR_COMPRESSION = 'COMPRESSION'
HDR_OLDFILEUID  = 'OLDFILEUID'
HDR_NEWFILEUID  = 'NEWFILEUID'

HDR_FIELDS_V1 = [HDR_OFXHEADER, HDR_DATA, HDR_VERSION, HDR_SECURITY,
        HDR_ENCODING, HDR_CHARSET, HDR_COMPRESSION, HDR_OLDFILEUID,
        HDR_NEWFILEUID]

HDR_FIELDS_V2 = [HDR_OFXHEADER, HDR_VERSION, HDR_SECURITY, HDR_OLDFILEUID,
        HDR_NEWFILEUID]

OFX_HEADER_100 = \
'''OFXHEADER:100
DATA:OFXSGML
VERSION:{version}
SECURITY:NONE
ENCODING:USASCII
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE
'''

OFX_HEADER_200 = \
'''<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<?OFX OFXHEADER="200" VERSION="{version}" SECURITY="NONE" OLDFILEUID="NONE"
NEWFILEUID="NONE"?>
'''

REQ_NAME_GET_ROOT     = 'GET /'
REQ_NAME_GET_OFX      = 'GET OFX Path'
REQ_NAME_POST_OFX     = 'POST OFX Path'
REQ_NAME_OFX_EMPTY    = 'OFX Empty'
REQ_NAME_OFX_PROFILE  = 'OFX PROFILE'
REQ_NAME_OFX_ACCTINFO = 'OFX ACCTINFO'

REQ_NAMES = [
    REQ_NAME_GET_ROOT,
    REQ_NAME_GET_OFX,
    REQ_NAME_POST_OFX,
    REQ_NAME_OFX_EMPTY,
    REQ_NAME_OFX_PROFILE,
    REQ_NAME_OFX_ACCTINFO
]

REQ_METHODS = {
    REQ_NAME_GET_ROOT:     'GET',
    REQ_NAME_GET_OFX:      'GET',
    REQ_NAME_POST_OFX:     'POST',
    REQ_NAME_OFX_EMPTY:    'POST',
    REQ_NAME_OFX_PROFILE:  'POST',
    REQ_NAME_OFX_ACCTINFO: 'POST'
}

#
# Helper Functions
#

def _print_http_response(res):
    print("===Request Headers===")
    print(dict(res.request.headers))
    print("===Request Body===")
    print(res.request.body)
    print("=== Response Status ===")
    print(res.status_code)
    print("=== Response Headers ===")
    print(dict(res.headers))
    print("=== Response Body ===")
    print(res.text)

#
# Public Functions
#

def dt_now():
    # Example: 20170616141327.123[-7:MST]
    return time.strftime("%Y%m%d%H%M%S.123[-7:MST]", time.localtime())


def uid():
    # Example: C1B7C870-7CB2-1000-BD91-E1E23E560026
    return str(uuid4()).upper()


def is_ofx_response(resp_body):
    ret = False

    # Version 1 Header
    if resp_body.startswith('OFXHEADER'):
        ret = True

    # Version 2 Header
    if resp_body.find('<?OFX OFXHEADER') != -1:
        ret = True

    return ret


class OFXServerInstance():
    '''
    Representation of an OFX server
    '''

    def __init__(self, ofxurl, fid, org):
        self.ofxurl = ofxurl
        self.fid = fid if fid else ''
        self.org = org if org else ''


class OFXTestClient():

    _payload_func = {}

    # Whether to print to stdout
    _output = True

    cache = {}

    def __init__(self,
            timeout=(3.2, 27),
            wait=0,
            use_cache=False,
            output=False,
            version='102'
            ):
        self.timeout = timeout
        self.wait = wait
        self.use_cache = use_cache
        self._output=output
        self.version = version

        if self.version[0] == '1':
            self.ofxheader = OFX_HEADER_100.format(version=self.version)
            self.content_type = 'text/sgml'
        elif self.version[0] == '2':
            self.ofxheader = OFX_HEADER_200.format(version=self.version)
            self.content_type = 'text/xml'
        else:
            raise ValueError(
                    'Unknown OFX version number {}'.format(self.version))

    def call_url_cached(self, url, tlsverify, body, method):
        '''
        return (request.response, boolean) - Response and whether it was
                cached.
        '''

        if method not in ['GET', 'POST']:
            raise ValueError("Method must be 'GET' or 'POST'")

        # Impersonate PFM
        headers = {
                'User-Agent': USER_AGENT,
                }

        if method == 'POST':
            headers['Content-Type'] = CONTENT_TYPE

        # Simple in memory cache to avoid duplicate calls to the same URL.
        try:
            r = self.cache[url]
            return (r, True)
        except KeyError:
            pass

        if self._output: print("{}".format(url))
        try:
            if method == 'GET':
                r = requests.get(
                        url,
                        headers=headers,
                        timeout=self.timeout,
                        verify=tlsverify
                        )
            elif method == 'POST':
                r = requests.post(
                        url,
                        headers=headers,
                        timeout=self.timeout,
                        verify=tlsverify,
                        data=body
                        )
            if self.use_cache:
                self.cache[url] = r
            return (r, False)
        except requests.ConnectionError as ex:
            if self._output: print('\tConnectionError: {}'.format(ex))
            # Set cache, but empty, to avoid further calls this run
            # Still cache connection errors even if use_cache == False
            self.cache[url] = None
        except requests.exceptions.ReadTimeout as ex:
            if self._output: print('\tConnectionError: {}'.format(ex))
            if wait > 0:
                if self._output:
                    print('\tWaiting for {} seconds'.format(self.wait))
                time.sleep(self.wait)

        return (None, False)

    def call_url_interactive(self, ofxurl, payload, method):
        res, was_cached = self.call_url_cached(
                ofxurl,
                True,
                payload,
                method
                )

        # Connection was completed successfully
        if res is not None:
            _print_http_response(res)

    def send_req(self, req_name, si):
        '''
        Send a pre-defined request to the OFX server.
        '''

        res = None

        if req_name == REQ_NAME_OFX_PROFILE:
            res, was_cached = self.call_url_cached(
                    si.ofxurl,
                    True,
                    self.get_profile_payload(si),
                    REQ_METHODS[req_name]
                    )
        else:
            raise ValueError('Unknown request name: {}'.format(req_name))

        return res

    def _get_signonmsg_anonymous_payload(self, si):

        if self.content_type == 'text/sgml':
            ofx_fi_fmt =  \
'''<FI>
<ORG>{org}
<FID>{fid}
</FI>
'''

            ofx_signon_fmt = \
'''<SIGNONMSGSRQV1>
<SONRQ>
<DTCLIENT>{dt}
<USERID>anonymous00000000000000000000000
<USERPASS>anonymous00000000000000000000000
<GENUSERKEY>N
<LANGUAGE>ENG
{fi}<APPID>QWIN
<APPVER>2700
</SONRQ>
</SIGNONMSGSRQV1>'''

        elif self.content_type == 'text/xml':
            ofx_fi_fmt =  \
'''<FI>
<ORG>{org}</ORG>
<FID>{fid}</FID>
</FI>
'''

            ofx_signon_fmt = \
'''<SIGNONMSGSRQV1>
<SONRQ>
<DTCLIENT>{dt}</DTCLIENT>
<USERID>anonymous00000000000000000000000</USERID>
<USERPASS>anonymous00000000000000000000000</USERPASS>
<GENUSERKEY>N</GENUSERKEY>
<LANGUAGE>ENG</LANGUAGE>
{fi}<APPID>QWIN</APPID>
<APPVER>2700</APPVER>
</SONRQ>
</SIGNONMSGSRQV1>'''

        if si is None:
            fi = ''
        else:
            fi = ofx_fi_fmt.format(
                fid=si.fid,
                org=si.org
                )

        frag = ofx_signon_fmt.format(
                dt=dt_now(),
                fi=fi
                )
        return frag

    def get_empty_payload(self, si):
        return ''

    def get_ofx_empty_payload(self, si):

        ofx_body = \
'''<OFX>
</OFX>
'''
        return "{}{}{}".format(self.ofxheader, '\n', ofx_body)

    def get_profile_payload(self, si):

        if self.content_type == 'text/sgml':
            ofx_body_fmt = \
'''<OFX>
{signonmsg}
<PROFMSGSRQV1>
<PROFTRNRQ>
<TRNUID>{uid}
<PROFRQ>
<CLIENTROUTING>MSGSET
<DTPROFUP>19900101
</PROFRQ>
</PROFTRNRQ>
</PROFMSGSRQV1>
</OFX>
'''

        elif self.content_type == 'text/xml':
            ofx_body_fmt = \
'''<OFX>
{signonmsg}
<PROFMSGSRQV1>
<PROFTRNRQ>
<TRNUID>{uid}</TRNUID>
<PROFRQ>
<CLIENTROUTING>MSGSET</CLIENTROUTING>
<DTPROFUP>19900101</DTPROFUP>
</PROFRQ>
</PROFTRNRQ>
</PROFMSGSRQV1>
</OFX>
'''

        body = ofx_body_fmt.format(
                signonmsg=self._get_signonmsg_anonymous_payload(si),
                uid=uid())
        return "{}{}{}".format(self.ofxheader, '\n', body)

    def get_acctinfo_payload(self, si):
        '''
        ACCTINFO Request payload
        '''

        ofx_body_fmt = \
'''<OFX>
{signonmsg}
<SIGNUPMSGSRQV1>
<ACCTINFOTRNRQ>
<TRNUID>{uid}
<ACCTINFORQ>
<DTACCTUP>19900101
</ACCTINFORQ>
</ACCTINFOTRNRQ>
</SIGNUPMSGSRQV1>
</OFX>
'''

        body = ofx_body_fmt.format(
                signonmsg=self._get_signonmsg_anonymous_payload(si),
                uid=uid())
        return "{}{}{}".format(self.ofxheader, '\n', body)

    def get_invstmtrn_payload(self, si, brokerid, acctid):
        '''
        INVSTMTTRRQ Request payload
        '''

        ofx_body_fmt = \
'''<OFX>
{signonmsg}
<INVSTMTMSGSRQV1>
<INVSTMTTRNRQ>
<TRNUID>{uid}
<INVSTMTRQ>
<INVACCTFROM>
<BROKERID>{broker_id}
<ACCTID>{acct_id}
</INVACCTFROM>
<INCTRAN>
<INCLUDE>Y
</INCTRAN>
<INCOO>Y
<INCPOS>
<INCLUDE>Y
</INCPOS>
<INCBAL>Y
</INVSTMTRQ>
</INVSTMTTRNRQ>
</INVSTMTMSGSRQV1>
</OFX>
'''
        body = ofx_body_fmt.format(
                signonmsg=self._get_signonmsg_anonymous_payload(si),
                uid=uid(),
                broker_id=brokerid,
                acct_id = acctid)

        return "{}{}{}".format(self.ofxheader, '\n', body)


class OFXFile():
    '''
    Read and parse an OFX file.
    '''

    _file_str = ''

    headers = {}
    version = None

    def __init__(self, file_str):
        self._file_str = file_str

        self._convert_newlines()
        self._parse_header()

    def _convert_newlines(self):
        '''
        Convert from network newlines to platform newlines.

        For now, just blindly Windows to Unix.
        '''

        self._file_str = self._file_str.replace('\r\n', '\n')

    def _parse_header(self):
        # Parse Version 1 Header

        # Example:
        #
        # OFXHEADER:100
        # DATA:OFXSGML
        # VERSION:102
        # SECURITY:NONE
        # ENCODING:USASCII
        # CHARSET:1252
        # COMPRESSION:NONE
        # OLDFILEUID:NONE
        # NEWFILEUID:NONE

        if self._file_str.startswith('OFXHEADER'):
            # Assume well formed and parse based on NEWLINES
            for line in self._file_str.splitlines():
                # End of header
                if line == '' or line.startswith('<OFX>') or len(line) > 13:
                    break
                [k,v] = line.split(':')
                self.headers[k] = v

            try:
                self.version = self.headers[HDR_VERSION]
            except KeyError:
                raise ValueError("Parse Error: No version")

        # Parse Version 2 Header

        # Example:
        # <?OFX OFXHEADER="200" VERSION="203" SECURITY="NONE" OLDFILEUID="NONE" NEWFILEUID="NONE"?>

        elif self._file_str.find('<?OFX OFXHEADER') != -1:
            # Python (as of 3.7) has no way to read prolog declarations.
            # https://bugs.python.org/issue24287
            # So don't bother parsing as XML, just use a regex to read the
            # OFX header.

            # TODO: Pull ENCODING out of <?xml> declaration

            rpat = r'<\?OFX OFXHEADER="(?P<OFXHEADER>\d+)" VERSION="(?P<VERSION>\d+)" SECURITY="(?P<SECURITY>\w+)" OLDFILEUID="(?P<OLDFILEUID>\w+)" NEWFILEUID="(?P<NEWFILEUID>\w+)"\?>'

            match = re.search(rpat, self._file_str)
            if not match:
                raise ValueError("Parse Error: Unable to parse V2 header with regex")
            for field in HDR_FIELDS_V2:
                self.headers[field] = match.group(field)

            try:
                self.version = self.headers[HDR_VERSION]
                parsed = True
            except KeyError:
                raise ValueError("Parse Error: No version")

        else:
            raise ValueError("Parse Error: Unable to parse header")