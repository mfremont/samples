"""
Script for searching and reporting on cases in the San Mateo Superior
Court Open Access system.

When run from the shell, the script expects that stdin contains search
strings such as case number or party names, one query per line. The -s
and -r switches control how the script interprets the input and the type
of output generated.

-s (alone) = search mode -> outputs case numbers that match the input queries

    example:

    echo "redus woodland" | python smcourt.py -s

-s -r -> search and produce a report that summarizes the matching cases

    example:
    
    echo "redus woodland" | python smcourt.py -s -r
    
-r -> produce a report that summarizes the case numbers on stdin

    example:
    
    echo "CLJ204977" | python smcourt.py -r
    
If you don't already have BeautifulSoup and mechanize installed, download and
install them with pip.

Copyright (c) 2008-2012 Matthew Fremont. All rights reserved.
"""

import BeautifulSoup
import mechanize

import urllib
import socket
import errno
import re
import sys
import traceback
import optparse
import fileinput
import itertools

DEFAULT_HEADERS = {
    'Accept': 'text/xml,application/xml,application/xhtml+xml,text/html;q=0.9,text/plain;q=0.8',
    'User-Agent': 'Mozilla/5.0 (Macintosh; U; Intel Mac OS X; en-US; rv:1.8.1.2) Gecko/20070219 Firefox/2.0.0.2',
    'Accept-Language': 'en-us,en;q=0.5',
    'Keep-Alive': '300',
    'Connection': 'keep-alive',
    }

CASEREPORT_URL = 'http://openaccess1.sanmateocourt.org/openaccess/civil/casereport.asp'
LOGIN_URL = 'http://openaccess1.sanmateocourt.org/openaccess/CIVIL/'
MIDX_SEARCH_URL = 'http://www.sanmateocourt.org/midx/index.php'
#OA_SEARCH_URL = 'http://openaccess1.sanmateocourt.org/openaccess/CIVIL/default.asp'
OA_SEARCH_URL = 'http://openaccess1.sanmateocourt.org/openaccess/CIVIL/civilnames.asp'

class MidxResults(object):
    """
    The results of a MIDX search. This class encapsulates the extraction
    of case numbers and the next page URL from the HTML of a MIDX search
    result page.
    """
    CASE_NUM_HEADING = re.compile('Case Number')
    
    def __init__(self, html):
        """
        Initializes the instance from a string or file-like stream of HTML.
        """
        self.soup = BeautifulSoup.BeautifulSoup(html)
        
    def cases(self):
        """
        Extracts the case numbers from the HTML and returns them as a list.
        If no cases are found, returns an empty list.
        """
        data = []
        try:
            tr = self.soup.find('td',text=self.CASE_NUM_HEADING).findParent('tr')
            while tr:
                data.append(map(flatten,tr.findAll('td',recursive=False)))
                tr = tr.findNextSibling('tr')
        except AttributeError:
            # end of results
            pass
        return data
    
    def next_page_url(self, page_num):
        """
        Extracts the URL for results page corresponding to page_num from this
        result, returning the URL as a string. If no URL is found returns an
        empty string.
        """
        a = self.soup.find('a',title=re.compile('Goto page %d' % page_num))
        if a:
            return a['href']
        else:
            return ''


class OpenAccessResults(object):
    """
    The results of an Open Access search. This class encapsulates the
    extraction of case numbers and the next page URL from the HTML of an
    Open Access search result page.
    """
    CASE_NUM_HEADING = re.compile('Case Number')

    def __init__(self, html):
        """
        Initializes the instance from a string or file-like stream of HTML.
        """
        self.soup = BeautifulSoup.BeautifulSoup(html)
        
    def cases(self):
        """
        Extracts the case numbers from the HTML and returns them as a list.
        If no cases are found, returns an empty list.
        """
        field_names = []
        data = []
        try:
            tr = self.soup.find('td',text=self.CASE_NUM_HEADING).findParent('tr')
            while tr:
                data.append(map(flatten,tr.findAll('td',recursive=False)))
                tr = tr.findNextSibling('tr')
        except AttributeError:
            # end of results
            pass
        return data
    

class CaseReport(object):
    """
    Open Access case report. This class encapsulates the extraction of key
    attributes from the HTML of an Open Access case report page.
    """
    RE_COMPLAINT_STATUS = re.compile('Complaint(\s|&nbsp;)+Status:')
    RE_COMPLAINT_TYPE = re.compile('Complaint(\s|&nbsp;)+Type:')
    RE_FILING_DATE = re.compile('Filing(\s|&nbsp;)+Date:')
    RE_PARTY_NAME = re.compile('Party(\s|&nbsp;)+Name')
    RE_DAILY_RENTAL = re.compile('DAILY(\s|&nbsp;)+RENTAL')
    RE_AMOUNT = re.compile('\$?([0-9]+\.[0-9]+)')
    RE_ADDRESS = re.compile('ADDRESS (.*)')
    RE_DEFAULT_JUDGEMENT = re.compile('JUDGMENT( |&nbsp;)+AFTER( |&nbsp;)+DEFAULT')
    RE_JUDGEMENT_FOR = re.compile('Judgment(\s|&nbsp;)+For')
    RE_DATE = re.compile('\d+/\d+/\d+')
    RE_ZIPCODE = re.compile('\d{5}')
    
    def __init__(self, html):
        """
        Initializes the instance from a file-like stream of HTML.
        """
        htmllines = html.readlines()
        # skip over wonky script tag that confused BeautifulSoup
        html = '\n'.join(itertools.chain(htmllines[:21],htmllines[179:]))
        self.soup = BeautifulSoup.BeautifulSoup(html)
        
    def complaint_type(self):
        """
        Extracts the complaint type from the HTML and returns it as a string.
        If the complaint type is not found, an empty string is returned.
        """
        elem = self.soup.find('td', text=self.RE_COMPLAINT_TYPE)
        if elem and isinstance(elem, BeautifulSoup.Comment):
            # case type is in markup embedded in comment. parse that.
            soup = BeautifulSoup.BeautifulSoup(elem)
            elem = soup.find('td', text=self.RE_COMPLAINT_TYPE)
        if elem:
            return flatten(elem.findParent('td').findNextSibling('td'))
        else:
            return ''
        
    def filing_date(self):
        """
        Extracts the filing date from the HTML and returns it as a string.
        If the filing date is not found, an empty string is returned.
        """
        elem = self.soup.find('td', text=self.RE_FILING_DATE)
        if elem:
            return flatten(elem.findParent('td').findNextSibling('td'))
        else:
            return ''
        
    def status(self):
        """
        Returns status ("ACTIVE", "Judgement", etc) and date, if present
        in the Complain Status cell of the case report. Sometimes the
        case report still contains "ACTIVE" even after a judgement has
        been entered. In this situation the party status is queried.
        """
        complaint_status = ('', '')
        elem = self.soup.find('td', text=self.RE_COMPLAINT_STATUS)
        if elem:
            status_str = flatten(elem.findParent('td').findNextSibling('td'))
            m = self.RE_DATE.search(status_str)
            if m:
                # status and date
                complaint_status = (status_str[:m.start()].strip(), m.group())
            else:
                # status only
                complaint_status = (status_str.strip(), '')
        if complaint_status[0].upper() == 'ACTIVE':
            # check parties table in case a judgement has been entered
            parties = self.parties('PLAINTIFF')
            if parties:
                status_elem = parties[0][2].split()
                if len(status_elem) == 3:
                    complaint_status = (status_elem[0], status_elem[2])
        return complaint_status

    def parties_table(self):
        """
        Extracts the HTML table element that lists the parties in the
        case, returning it as a BeautifulSoup parse tree. If the table
        is not found, returns None.
        """
        elem = self.soup.find('td', text=self.RE_PARTY_NAME)
        if elem:
            return elem.findParent('table')
        else:
            return None
        
    def parties(self, party_type):
        """
        Extracts the name, attorney, and status for each party matching
        the type specified by the party_type string (e.g. "PLAINTIFF",
        "DEFENDANT"), returning a list of lists. Each entry in the list
        contains the party name, name of the representing attorney, and
        the status for that plaintiff. If there is no match for the
        party_type, or the parties table is not present, returns an
        empty list.
        """
        table = self.parties_table()
        pdata = []
        if table:
            for elem in table.findAll('td', text=re.compile(party_type)):
                tr = elem.findParent('tr')
                pdata.append(map(flatten,tr.findAll('td',recursive=False)[2:5]))
        return pdata        
                
    def daily_rental_value(self):
        """
        Extracts the daily rental value from the body of the case report,
        returning it as a string. This value is only present in unlawful
        detainer cases. If the daily rental value cannot be found, an
        empty string is returned instead.
        """
        for elem in self.soup.findAll('td', text=self.RE_DAILY_RENTAL):
            m = self.RE_AMOUNT.search(elem)
            if m:
                return m.group(1)
        return ''
    
    def address(self):
        """
        Returns the string following "ADDRESS" in the body of the case
        report. This appears in unlawful detainer cases. If this string
        cannot be found, and empty string is returned instead.
        """
        for elem in self.soup.findAll('td', text=self.RE_ADDRESS):
            m = self.RE_ADDRESS.search(elem)
            if m:
                address_str = m.group(1)
                m = self.RE_ZIPCODE.search(address_str)
                if m:
                    # return portion of string up to and including zip code
                    return address_str[:m.end()]
                else:
                    return address_str
        return ''
    
    def is_default_judgement(self):
        """
        Returns True if the body of the case report contains
        the phrase "JUDGEMENT AFTER DEFAULT", False otherwise.
        """
        return bool(self.soup.findAll('td', text=self.RE_DEFAULT_JUDGEMENT))
#         for elem in self.soup.findAll('td', text=self.RE_DEFAULT_JUDGEMENT):
#             parent = elem.findParent('td')
#             if parent and flatten(parent.findNextSibling('td')).find('JUDGMENT') != -1:
#                 return True
#         return False
        
    def judgement_for(self):
        """
        Searches the parties table for an indication that a judgement has been
        entered in favor of a particular party. If so, the party type string
        (e.g. "PLAINTIFF" or "DEFENDANT") is returned; otherwise, an empty
        string is returned.
        """
        table = self.parties_table()
        if not table:
            # could not find parties table
            return ''
        tr = table.find('tr')
        while tr:
            if tr.find('td', text=self.RE_JUDGEMENT_FOR):
                return flatten(tr.findAll('td', recursive=False)[1])
            tr = tr.findNextSibling('tr')
        return ''
        
        
WS = re.compile('(\s|&nbsp;)+')
    
def flatten(node):
    """
    Returns the text in the parse tree represented by node. Runs of whitespace
    are collapsed and leading and trailing whitespace is removed from each text
    node found.
    """
    text = []
    if isinstance(node, BeautifulSoup.NavigableString):
        return WS.sub(' ',node.string).strip()
    else:
        for child in node:
            text.append(flatten(child))
    return ''.join(text)


def new_session(login_url=LOGIN_URL):
    """
    Returns a mechanize.Browser() instance that has been initialized by making
    a request for LOGIN_URL to obtain the required session cookie.
    """
    browser = mechanize.Browser()
    browser.addheaders = DEFAULT_HEADERS.items()
    response = browser.open(LOGIN_URL)
    response.close()
    return browser
    

def midx_search(browser, q):
    """
    Submits the query q to the MIDX search interface using the meachanize.Browser
    instance br and returns a list of the flattened rows from the result table.
    The first row contains the field names from the table.
    
    MIDX quirks:
    
    1. "360 okeefe" will match both "360 O'KEEFE" and "360 OKEEFE"
    2. "360 e okeefe" will match "360 E OKEEFE" and 360 E. OKEEFE" but not
       "360 E O'KEEFE"
    3. it will not find any matches for a name with a "/" like "45/55 Newell";
       Use the open access search instead.
    """
    browser.open(MIDX_SEARCH_URL)
    browser.select_form(name='midxsearch')
    browser['aname'] = q
    response = browser.submit()
    page_num = 1
    cases = []
    while True:
        results = MidxResults(response)
        data = results.cases()
        if cases:
            # skip field names
            cases.extend(data[1:])
        else:
            cases.extend(data)
        page_num += 1
        next_url = results.next_page_url(page_num)
        if next_url:
            response = browser.follow_link(url=next_url)
        else:
            break
    return cases


def openaccess_search(browser, q):
    """
    Submits the query q to the open access search interface using the 
    meachanize.Browser instance br and returns a list of the flattened rows 
    from the result table. The first row contains the field names from the table.
    """
    data = (
        ('deflastname', q.upper()), ('bus', 'Y'), ('courtcode', 'A'),
        ( 'filedatefrom', ''), ('filedateto', ''), ('limit', 1000),
        ('dsn', ''),
        )
    
    try:
        response = browser.open(OA_SEARCH_URL, urllib.urlencode(data))
        return OpenAccessResults(response).cases()
    except mechanize.HTTPError:
        pass
    return []

def open_case_report(br, casenum):
    """
    Opens a request to fetch the case report for casenum and returns the
    HTTP response. casenum should include the 3-letter prefix such
    as "CIV" or "CLJ".
    """
    data = { 'casetype': casenum[:3], 'casenumber': casenum[3:],
        'courtcode': 'A', 'dsn': '' }
    url = '?'.join((CASEREPORT_URL, urllib.urlencode(data)))
    return br.open(url)


def summarize_cases(browser, cases, complaint_type=None, delim='\t', header=True, out=sys.stdout):
    """
    Outputs a summary line to stdout for each of the case number
    identifiers in the cases list. The browser argument must be a properly
    initialized mechanize Browser instance.
    
    If the optional argument complaint_type is specified, only cases whose
    complaint type matches that argument will be be included in the output.
    
    The optional argument delim can be used to specify a field delimeter.
    By default, the fields are tab-separated.
    
    The optional argument header is used to control whether a header
    containing the field names is output at the start of the summary. By
    default, header=True.
    
    The optional argument out is used to specify a stream to which the
    summary is written. By default, output goes to sys.stdout.
    """
    if header:
        print >> out, delim.join(('Case','Type','Filing Date','Plaintiff','Attorney',
            'Defendant','Attorney','Status','Date','Judgement For','Default',
            'Daily Rental Value','Address'))
    for casenum in cases:
        try:
            cr = CaseReport(open_case_report(browser,casenum))
            if complaint_type and cr.complaint_type().find(complaint_type) == -1:
                # skip cases that do not contain complaint_type
                continue
            summary = [ casenum, cr.complaint_type(), cr.filing_date() ]
            for ptype in ('PLAINTIFF', 'DEFENDANT'):
                parties = cr.parties(ptype)
                if parties:
                    # transpose rows and columns
                    parties = zip(*parties)
                else:
                    parties = [ '', '', '' ]
                # name
                summary.append('; '.join(parties[0]))
                # attorney name
                summary.append('; '.join(parties[1]))
            summary.extend(cr.status())
            summary.append(cr.judgement_for())
            summary.append(cr.is_default_judgement() and 'DEFAULT' or '')
            summary.append(cr.daily_rental_value())
            summary.append(cr.address())
            
            print >> out, delim.join(summary)
        except:
            print >> sys.stderr, "Skipping case %s due to exception:" % casenum
            print >> sys.stderr, traceback.format_exc()

if __name__ == '__main__':
    parser = optparse.OptionParser()
    parser.add_option('-s','--search', dest='search', help='search for cases',
        action='store_true')
    parser.add_option('-r','--report', dest='report',
        help='output case summary report', action='store_true')
    parser.add_option('-c','--complaint-type', dest='complaint_type', default='',
        help='filter for complaint type')
    
    (options, args) = parser.parse_args()
    
    browser = new_session()

    rec = 0
    
    for line in fileinput.input(args):
        if options.search:
            q = line.strip()
            if q.find('/') == -1:
                cases = (c[0] for c in midx_search(browser, q)[1:])
            else:
                # use open access for queres with '/' since MIDX will fail
                cases = (c[4] for c in openaccess_search(browser, q)[1:])
            if options.report:
                summarize_cases(browser, cases, 
                    complaint_type=options.complaint_type,header=(rec==0))
                rec += 1
            elif cases:
                print '\n'.join(cases)
        elif options.report:
            summarize_cases(browser, [line.strip()], complaint_type=options.complaint_type,
                header=(rec==0))
            rec += 1

